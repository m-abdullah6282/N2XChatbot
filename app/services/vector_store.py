from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition,
    MatchValue, FilterSelector, PayloadSchemaType, IsEmptyCondition, PayloadField,
)
import uuid
import logging
import re
from app.config import QDRANT_URL, QDRANT_API_KEY
 
client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
logger = logging.getLogger(__name__)

COLLECTION_NAME = "knowledge_base"

# Contact/address signals. Queries containing these words always force the
# agent's CONTACT-typed chunks into the retrieval context regardless of the
# vector score, so "contact/baat/office/address/kaha" questions never fail.
CONTACT_QUERY_WORDS = {
    "office", "address", "location", "contact", "kaha", "kahan",
    "baat", "raabta", "rabta", "milne", "milo", "email", "phone",
    "number", "call", "where", "head",
}

_CONTACT_CHUNK_PATTERN = re.compile(
    r"(email|e-?mail|phone|whatsapp|contact|address|office|location|"
    r"head ?office|raabta|plot|street|www\.[a-z0-9-]+|\.com\b|"
    r"\+[\d][\d\s-]{5,}|\b\d{4,}[-.\s]?\d{3,})",
    re.IGNORECASE,
)

_CONTACT_SIGNAL_WORDS = (
    "email", "phone", "whatsapp", "contact", "address", "office",
    "location", "raabta", "plot", "street", "call",
)


def is_contact_query(query_text: str) -> bool:
    """True when a user question looks like a contact/address request."""
    tokens = set(re.findall(r"[a-z]+", (query_text or "").lower()))
    return bool(tokens & CONTACT_QUERY_WORDS)


def is_contact_chunk(text: str) -> bool:
    """True when a knowledge chunk carries contact details (email/phone/
    address/location): such chunks are force-included for contact queries."""
    return bool(_CONTACT_CHUNK_PATTERN.search(text or ""))


def _contact_score(text: str) -> int:
    """Rough relevance of a chunk to contact queries: the number of distinct
    contact signals it mentions."""
    lower = (text or "").lower()
    return sum(1 for word in _CONTACT_SIGNAL_WORDS if word in lower)


def create_collection_if_not_exists():
    collections = client.get_collections().collections
    collection_names = [c.name for c in collections]

    if COLLECTION_NAME not in collection_names:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE)
        )

    ensure_filename_index()
    ensure_agent_index()
    ensure_contact_index()

def ensure_filename_index():
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="filename",
        field_schema=PayloadSchemaType.KEYWORD,
    )

def ensure_agent_index():
    try:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="agent_id",
            field_schema=PayloadSchemaType.INTEGER,
        )
    except Exception:
        pass

CONTACT_INDEX_KEYWORD = "is_contact"

def ensure_contact_index():
    try:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=CONTACT_INDEX_KEYWORD,
            field_schema=PayloadSchemaType.INTEGER,
        )
    except Exception:
        pass

def store_chunks(chunks: list[str], embeddings: list[list[float]], filename: str, agent_id: int | None = None):
    points = []
    for chunk, embedding in zip(chunks, embeddings):
        payload = {
            "text": chunk,
            "filename": filename,
            CONTACT_INDEX_KEYWORD: 1 if is_contact_chunk(chunk) else 0,
        }
        if agent_id is not None:
            payload["agent_id"] = agent_id
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload=payload
        )
        points.append(point)

    client.upsert(collection_name=COLLECTION_NAME, points=points)

def _agent_conditions(filename: str, agent_id: int | None) -> list:
    conditions = [FieldCondition(key="filename", match=MatchValue(value=filename))]
    if agent_id is not None:
        conditions.append(FieldCondition(key="agent_id", match=MatchValue(value=agent_id)))
    else:
        # Points stored without an agent_id payload key. `is_empty` matches
        # both missing and null values; `is_null` does NOT match missing keys.
        conditions.append(IsEmptyCondition(is_empty=PayloadField(key="agent_id")))
    return conditions

def delete_points_by_filename(filename: str, agent_id: int | None = None):
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(
                must=_agent_conditions(filename, agent_id)
            )
        ),
    )

def delete_points_by_agent(agent_id: int):
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(
                must=[FieldCondition(key="agent_id", match=MatchValue(value=agent_id))]
            )
        ),
    )

def _scope_filter(agent_id: int | None) -> Filter:
    """Filter that limits retrieval to the right knowledge scope:
    - a specific agent: that agent's chunks PLUS the shared (agent_id empty) ones
    - no agent (shared chat): only the shared chunks"""
    if agent_id is not None:
        return Filter(
            should=[
                IsEmptyCondition(is_empty=PayloadField(key="agent_id")),
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
            ]
        )
    return Filter(
        must=[IsEmptyCondition(is_empty=PayloadField(key="agent_id"))]
    )


def search_similar_chunks(query_embedding: list[float], top_k: int = 3, agent_id: int | None = None, score_threshold: float = 0.15, query_text: str | None = None) -> tuple[list[dict], bool]:
    """Return matching chunks and whether Qdrant was reachable.

    Each chunk dict carries the chunk ``text`` and its vector ``score`` so
    callers can prioritise the most relevant content when truncating the LLM
    context (a 413 error occurs when the combined context grows too large).

    The embedding model is English-only, so Roman Urdu queries score poorly
    against English sections. ``query_text`` enables two keyword boosts:
    1. a heading keyword boost (query word matches a chunk's heading/content),
    2. a CONTACT boost: when the query asks about contact/address/office/baat,
       contact-typed chunks are force-included regardless of vector score.
    """
    query_filter = _scope_filter(agent_id)
    try:
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=query_filter,
            score_threshold=score_threshold,
        )
    except Exception:
        logger.exception("Qdrant search failed; knowledge retrieval is unavailable")
        return [], False

    chunks = [
        {"text": result.payload.get("text", ""), "score": float(result.score)}
        for result in results
        if (result.payload or {}).get("text")
    ]

    if query_text:
        # Contact/address queries: force the agent's CONTACT chunks in even when
        # their vector score is low, so "baat/office/address/kaha" never fails.
        if is_contact_query(query_text):
            chunks = _merge_contact_chunks(chunks, query_filter, query_text, top_k)

        heading_match = _heading_keyword_match(query_text, query_filter)
        if heading_match and heading_match not in [c["text"] for c in chunks]:
            top_score = chunks[0]["score"] if chunks else 0.0
            chunks.insert(0, {"text": heading_match, "score": top_score + 1.0})
            chunks = chunks[: top_k + 1]

    return chunks, True


def _merge_contact_chunks(chunks: list[dict], query_filter: Filter, query_text: str, top_k: int) -> list[dict]:
    """Prepend up to two contact-typed chunks for contact/address queries, then
    cap the result at top_k + inserted chunks (deduping against the semantic
    results). A failure here is non-fatal: plain retrieval still proceeds."""
    try:
        contact_filter = Filter(
            must=[FieldCondition(key=CONTACT_INDEX_KEYWORD, match=MatchValue(value=1))]
            + (list(query_filter.must) if query_filter.must else []),
            should=query_filter.should,
        )
        result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=contact_filter,
            limit=20,
            with_payload=True,
        )
    except Exception:
        logger.exception("Contact chunk fetch failed")
        return chunks

    candidates = [
        (point.payload or {}).get("text", "")
        for point in result[0]
        if (point.payload or {}).get("text")
    ]
    candidates.sort(key=lambda text: _contact_score(text), reverse=True)

    existing = {c["text"] for c in chunks}
    top_score = chunks[0]["score"] if chunks else 0.0
    inserted = 0
    for text in candidates:
        if text in existing:
            continue
        existing.add(text)
        chunks.insert(0, {"text": text, "score": top_score + 1.0})
        inserted += 1
        if inserted >= 2:
            break
    if inserted:
        chunks = chunks[: top_k + inserted]
    return chunks


def _heading_keyword_match(query_text: str, query_filter: Filter | None, exclude_contact: bool = True) -> str | None:
    """Return the first chunk whose heading or leading content matches a
    significant query word.

    A "significant" word is 3+ alphanumeric characters; the match is
    case-insensitive against the chunk's heading and first few content lines
    (headings only were too strict for facts like ``20+ Clients`` that live in
    the body of a section). Without a word-boundary match, "cricket" inside
    "info@cricket.com" would let a contact chunk answer the wrong question, so
    CONTACT chunks are skipped here (the dedicated contact merge handles them)
    unless the query itself is a contact request.
    """
    tokens = {
        token
        for token in re.findall(r"[a-zA-Z0-9]+", query_text.lower())
        if len(token) >= 3
    }
    if not tokens:
        return None
    contact_query = is_contact_query(query_text)
    try:
        # Bounded scan: limit=1000 fetches up to 1000 full payloads in one
        # response, which is a big transfer for a keyword pre-check and can
        # push this call out of the /chat request budget. 100 points are
        # plenty to surface a matching heading section.
        result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=query_filter,
            limit=100,
            with_payload=True,
        )
        for point in result[0]:
            payload = point.payload or {}
            if exclude_contact and not contact_query and payload.get(CONTACT_INDEX_KEYWORD) == 1:
                continue
            text = payload.get("text", "")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            haystack = "\n".join(lines[:6]).lower()
            if haystack and any(token in haystack for token in tokens):
                return text
    except Exception:
        logger.exception("Heading keyword scan failed")
        return None
    return None
