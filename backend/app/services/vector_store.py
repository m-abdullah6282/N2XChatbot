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

# Contact/address signals are matched WORD-BOUNDED and require a real address
# (an email address or a phone/cell number) or TWO distinct contact keywords.
# This avoids the false positives that a naive substring flag produced on
# ordinary content: "email" inside "CRM, email, quotations", "plot" inside
# "Matplotlib", or a bare "www." project link never mark a chunk as contact.
_CONTACT_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CONTACT_PHONE_RE = re.compile(r"(?<![\d-])\+?\d{1,3}[\s-]?\d{2,4}(?:[\s-]?\d{3,4}){1,2}(?![\d-])")
_CONTACT_KEYWORD_RE = re.compile(
    r"\b(?:email|e-?mail|phone|whatsapp|contact|address|office|location|"
    r"head ?office|raabta|street|plot|block|sector)\b",
    re.IGNORECASE,
)

_CONTACT_SIGNAL_WORDS = (
    "email", "phone", "whatsapp", "contact", "address", "office",
    "location", "raabta", "plot", "street", "call",
)

# Generic filler/question words that must NOT trigger the heading-keyword
# boost. Without this filter, an Urdu question like "aapka CEO kon hai?"
# would lexically match the first chunk containing "hai" (or "kon"), dragging
# an unrelated section into the retrieval context and making the bot answer
# from irrelevant content.
_HEADING_KEYWORD_STOPWORDS = {
    "hai", "ho", "hain", "tha", "thi", "the", "hoga", "hogi", "honge", "hon",
    "kon", "kaun", "kya", "kyu", "kion", "kyon", "kese", "kaise", "kesi", "kis",
    "konsa", "konsi", "karta", "karti", "karte", "karna", "karo", "karein",
    "kijiye", "karu", "kare", "aap", "aapka", "aapki", "aapke", "tum", "tumhara",
    "tumhari", "mujhe", "muje", "mere", "main", "mein", "hum", "humara", "humari",
    "mera", "meri", "is", "us", "ye", "yeh", "wo", "woh", "aur", "nahi", "na",
    "to", "bhi", "batao", "bataye", "btaiye", "batayen", "bolo", "du", "dijiye",
    "de", "do", "theek", "acha", "achha", "sahi", "chahiye", "kafi",
    "what", "when", "where", "why", "how", "who", "which", "whom", "whose",
    "does", "do", "did", "doing", "is", "are", "am", "was", "were", "be",
    "the", "and", "or", "of", "to", "for", "with", "please", "plz", "can",
    "tell", "give", "get", "have", "has", "had", "that", "this", "these",
    "those", "please", "hey", "hi", "hello",
}


def is_contact_query(query_text: str) -> bool:
    """True when a user question looks like a contact/address request."""
    tokens = set(re.findall(r"[a-z]+", (query_text or "").lower()))
    return bool(tokens & CONTACT_QUERY_WORDS)


# Dictionaries for Roman-Urdu/Hinglish -> English semantic normalization.
# The embedding model (all-MiniLM-L6-v2) is English-only, and common Hinglish
# filler/stop words ("jo", "kiye", "kara") drown the few English tokens in
# "projects k naam btao", pushing the query embedding well below the vector
# threshold. Normalization strips the filler and substitutes English keywords
# so the query semantically lands near its topic sections.
_NORMALIZE_PHRASES: list[tuple[str, str]] = [
    (r"\bnaam bata(?:o|au|ye)?\b", "names"),
    (r"\b(?:name|naam)s?\b", "names"),
    (r"\bnaam\b", "names"),
    (r"\bbt(?:a|ao|aiye|aye)?\b", "tell"),
    (r"\bbata(?:o|u|ye|yen|na)?\b", "tell"),
    (r"\bbtaiye\b", "tell"),
    (r"\btell\b", "tell"),
    (r"\bprojects?\b", "projects"),
    (r"\bprojcts?\b", "projects"),
    (r"\bporjects?\b", "projects"),
    (r"\bpojects?\b", "projects"),
    (r"\bproejcts?\b", "projects"),
    (r"\bkiye\b", "done"),
    (r"\bkya? work kiya\b", "projects worked on"),
    (r"\bjo\b", ""),
    (r"\bjojo\b", ""),
    (r"\blist\b", "list all"),
    (r"\btotal\b", "all"),
    (r"\bbt(?:a|ao)\b", "list all"),
    (r"\bkarnte\b", "does"),
    (r"\bkar?te\b", ""),
    (r"\bkarte\b", "do"),
    (r"\bkarta\b", "does"),
    (r"\bkarna\b", "do"),
    (r"\bhain\b", ""),
    (r"\bhai\b", ""),
    (r"\bho\b", ""),
    (r"\bthay\b", ""),
    (r"\bthe\b", ""),
    (r"\bgyei?\b", "went"),
    (r"\bgayi\b", "made"),
    (r"\bgya\b", "made"),
    (r"\bkiya\b", "did"),
    (r"\bkar(kar|akh)?\b", "did"),
    (r"\bse\b", ""),
    (r"\bko\b", ""),
    (r"\bbi\b", ""),
    (r"\bto\b", ""),
    (r"\bka\b", ""),
    (r"\bki\b", ""),
    (r"\bke\b", ""),
    (r"\bchahiye\b", "need"),
    (r"\bzabi\b", "service"),
    (r"\bservices?\b", "services"),
    (r"\bpricing\b", "pricing"),
    (r"\bprice\b", "pricing"),
    (r"\bdaam\b", "pricing"),
    (r"\bkitne\b", "how many"),
    (r"\bkitna\b", "how much"),
    (r"\bkitni\b", "how many"),
    (r"\bsaab\b", "all"),
    (r"\bsare\b", "all"),
    (r"\bsari\b", "all"),
    (r"\bsab\b", "all"),
    (r"\bportfolio\b", "portfolio"),
    (r"\bkaam\b", "projects"),
    (r"\bcompany\b", "company"),
    (r"\babout\b", "about"),
    (r"\bke baare mein\b", "about"),
    (r"\bkon\b", "who"),
    (r"\bkaun\b", "who"),
    (r"\bkya hai\b", "what is"),
    (r"\bkya hain\b", "what is"),
    (r"\bkaise\b", "how"),
    (r"\bkese\b", "how"),
    (r"\bkasai\b", "how"),
    (r"\bkyun\b", "why"),
    (r"\bkyu\b", "why"),
    (r"\bkab\b", "when"),
    (r"\bkahan\b", "where"),
    (r"\bkaha\b", "where"),
    (r"\bexperience\b", "experience"),
    (r"\bteam\b", "team"),
    (r"\bcontact\b", "contact"),
    (r"\bemail\b", "email"),
    (r"\bphone\b", "phone"),
    (r"\bnumber\b", "number"),
    (r"\baddress\b", "address"),
    (r"\boffice\b", "office"),
    (r"\blocation\b", "location"),
    (r"\bwebsite\b", "website"),
    (r"\blink\b", "link"),
    (r"\bsocial\b", "social media"),
    (r"\bhandle\b", "social media"),
    (r"\bprofile\b", "profile"),
]


def normalize_query(query_text: str) -> str:
    """Translate common Hinglish/Roman-Urdu fillers into English keywords so
    the (English-only) embedding model can match the query to its topic.

    Example:
      "projects k naam btao jo jo kiye"  ->  "projects k names tell  done"
      "pojects k naam btao"              ->  "pojects k names tell"

    Unknown words pass through untouched; the function is additive and never
    strips English content.
    """
    if not query_text:
        return query_text
    text = " " + query_text.lower().strip() + " "
    for pattern, replacement in _NORMALIZE_PHRASES:
        text = re.sub(pattern, f" {replacement} ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_contact_chunk(text: str) -> bool:
    """True when a knowledge chunk genuinely carries contact details.

    A chunk counts as contact only when it contains a real email address or a
    phone number, or when it mentions TWO DISTINCT contact keywords (e.g.
    "address" + "plot"). A single incidental keyword — "email" as a workflow
    feature, "Matplotlib" containing "plot" — never qualifies, because such
    false positives would hide ordinary content from the heading-keyword boost
    and paddle ordinary chunks into every contact answer.
    """
    text = text or ""
    if _CONTACT_EMAIL_RE.search(text) or _CONTACT_PHONE_RE.search(text):
        return True 
    keywords = {match.group(0).lower() for match in _CONTACT_KEYWORD_RE.finditer(text)}
    return len(keywords) >= 2


def _strong_contact_signal(text: str) -> bool:
    """A chunk carries an explicit email address or phone number."""
    return bool(
        (text or "")
        and (_CONTACT_EMAIL_RE.search(text) or _CONTACT_PHONE_RE.search(text))
    )


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

def store_chunks(
    chunks: list[str],
    embeddings: list[list[float]],
    filename: str,
    agent_id: int | None = None,
    document_id: int | None = None,
    owner_admin_id: int | None = None,
):
    """Store vector chunks in Qdrant. The payload carries every chunk's trace
    metadata: text, filename, contact flag, agent_id (shared when None),
    document_id, owner_admin_id and a zero-based chunk_index. document_id /
    owner_admin_id are informational only — authorization is always enforced
    server-side, never by trusting Qdrant metadata."""
    points = []
    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        payload = {
            "text": chunk,
            "filename": filename,
            CONTACT_INDEX_KEYWORD: 1 if is_contact_chunk(chunk) else 0,
            "chunk_index": index,
        }
        if agent_id is not None:
            payload["agent_id"] = agent_id
        if document_id is not None:
            payload["document_id"] = document_id
        if owner_admin_id is not None:
            payload["owner_admin_id"] = owner_admin_id
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
    """Retrieval scope is STRICTLY per-agent: an agent only ever sees vectors
    whose payload.agent_id equals its own id. There is intentionally NO
    shared/global knowledge scope, so NULL-agent vectors are never included in
    an agent's retrieval (they belong to no agent and must not leak).
    A request without an agent id receives nothing — it cannot scope itself to
    any agent's data, so it matches an impossible value."""
    if agent_id is not None:
        return Filter(
            must=[FieldCondition(key="agent_id", match=MatchValue(value=agent_id))]
        )
    return Filter(
        must=[FieldCondition(key="agent_id", match=MatchValue(value=-1))]
    )


# Aggregate/counting questions ask for a whole list ("how many", "list all",
# "kitne"), so the section whose heading matched must contribute its ENTIRE
# entry family (every project/job/product chunk), not just the container that
# carries the heading keyword.
_AGGREGATE_QUESTION_RE = re.compile(
    r"\b(how many|how much|list all|list|total|each|all|kitne|kitna|kitni|"
    r"kittne|saare|sab|tamam|poore)\b",
    re.IGNORECASE,
)

# A chunk whose first line is an ALL-CAPS block starts a NEW major section; the
# entry family of the matched section ends there.
_MAJOR_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9/& .(){}+:'%-]{2,}$")


def is_aggregate_question(query_text: str) -> bool:
    """True when the user wants a list/count (whole section), not one fact."""
    return bool(_AGGREGATE_QUESTION_RE.search(query_text or ""))


def _aggregate_section_family(matched_text: str, query_filter: Filter, limit: int = 6) -> list[str]:
    """Return the sibling entry chunks that follow a matched section container.

    When an aggregate question matches a section heading ("PROJECTS"),
    counting the entries requires the entries themselves — the child chunks
    stored right after the container in the same document. Chunks are ordered
    by their ``chunk_index`` payload (legacy uploads carry none and fall back
    to plain semantic retrieval). The family ends at the next ALL-CAPS major
    section heading.
    """
    try:
        page, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=query_filter,
            limit=200,
            with_payload=True,
        )
    except Exception:
        logger.exception("Aggregate family scan failed")
        return []
    points = [p for p in page if (p.payload or {}).get("text")]
    matched = next(
        (p for p in points if (p.payload or {}).get("text") == matched_text), None
    )
    if matched is None:
        return []
    matched_payload = matched.payload or {}
    matched_index = matched_payload.get("chunk_index")
    filename = matched_payload.get("filename")
    if matched_index is None or not filename:
        return []
    indexed: list[tuple[int, str]] = []
    seen_texts: set[str] = set()
    for point in points:
        payload = point.payload or {}
        text = payload.get("text", "")
        if (
            not text
            or payload.get("filename") != filename
            or payload.get("chunk_index") is None
            or text in seen_texts
        ):
            continue
        seen_texts.add(text)
        indexed.append((int(payload["chunk_index"]), text))
    family: list[str] = []
    for index, text in sorted(indexed):
        if index <= matched_index:
            continue
        if len(family) >= limit:
            break
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        if _MAJOR_HEADING_RE.match(first_line):
            break
        family.append(text)
    return family


def _expand_listing_cluster(chunks: list[dict], top_k: int) -> list[dict]:
    """Keep the extra chunks that scored close to the best result.

    Documents laid out as repeated entries (several projects, products, job
    roles, or simulation results) make their sections score within a narrow
    band; 'how many'/'list all' questions then need the whole band, not just
    the top few. When later chunks are within a relative band of the top score
    they are kept too, up to a small context budget. A document with one
    dominant match (the N2X services list, a lookup) expands by nothing.
    """
    if len(chunks) <= top_k:
        return chunks
    top = chunks[0]["score"]
    band = max(top * 0.65, top - 0.18)
    kept = chunks[:top_k]
    for chunk in chunks[top_k:]:
        if len(kept) >= top_k * 2:
            break
        if chunk["score"] >= band:
            kept.append(chunk)
    return kept


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
    Chunks whose scores cluster near the top result are also kept (listing
    support), so 'list all / how many' questions see the whole list.
    """
    if query_text:
        query_text = normalize_query(query_text)
    query_filter = _scope_filter(agent_id)
    try:
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            limit=max(top_k, 12),
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

    # Dedupe by content: identical text can exist as multiple points (e.g.
    # repeated uploads), which would otherwise flood the LLM context.
    seen: set[str] = set()
    unique_chunks: list[dict] = []
    for chunk in chunks:
        if chunk["text"] in seen:
            continue
        seen.add(chunk["text"])
        unique_chunks.append(chunk)
    chunks = unique_chunks

    # Listing support: several chunks tied near the top score means the answer
    # needs the whole cluster (all projects, all matches), not just top_k of
    # them. Kept short-list enumerations inside a bounded context budget.
    chunks = _expand_listing_cluster(chunks, top_k)

    if query_text:
        # Contact/address queries: force the agent's CONTACT chunks in even when
        # their vector score is low, so "baat/office/address/kaha" never fails.
        if is_contact_query(query_text):
            chunks = _merge_contact_chunks(chunks, query_filter, query_text, top_k)

        heading_match = _heading_keyword_match(query_text, query_filter)
        if heading_match:
            texts = {c["text"] for c in chunks}
            if heading_match not in texts:
                top_score = chunks[0]["score"] if chunks else 0.0
                chunks.insert(0, {"text": heading_match, "score": top_score + 1.0})
            # Listing/counting questions need the whole entry family of the
            # matched section (every project, not just the container that
            # carries the heading keyword).
            if is_aggregate_question(query_text):
                top_score = chunks[0]["score"] if chunks else 0.0
                for offset, family_text in enumerate(
                    _aggregate_section_family(heading_match, query_filter, limit=max(top_k * 2, 6))
                ):
                    if family_text in texts:
                        continue
                    texts.add(family_text)
                    chunks.append(
                        {"text": family_text, "score": top_score - 0.5 - offset * 0.1}
                    )

    chunks = chunks[: min(len(chunks), max(top_k * 2, 6))]

    return chunks, True


def _merge_contact_chunks(chunks: list[dict], query_filter: Filter, query_text: str, top_k: int) -> list[dict]:
    """Prepend up to two contact-typed chunks for contact/address queries, then
    cap the result at top_k + inserted chunks (deduping against the semantic
    results). A failure here is non-fatal: plain retrieval still proceeds.

    Contact chunks are identified at RUNTIME by scanning their text, because
    the stored ``is_contact`` payload flag predates some legacy uploads and
    cannot be relied on."""
    try:
        points: list = []
        next_offset = None
        while True:
            args: dict = dict(
                collection_name=COLLECTION_NAME,
                scroll_filter=query_filter,
                limit=200,
                with_payload=True,
            )
            if next_offset is not None:
                args["offset"] = next_offset
            page, next_offset = client.scroll(**args)
            points.extend(page)
            if not next_offset or len(points) >= 1000:
                break
    except Exception:
        logger.exception("Contact chunk fetch failed")
        return chunks

    candidates = []
    seen_texts: set[str] = set()
    for point in points:
        text = (point.payload or {}).get("text", "")
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        if is_contact_chunk(text) and (
            _contact_score(text) >= 1 or _strong_contact_signal(text)
        ):
            candidates.append(text)
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
        if len(token) >= 3 and token not in _HEADING_KEYWORD_STOPWORDS
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
            limit=300,
            with_payload=True,
        )
        for point in result[0]:
            payload = point.payload or {}
            if exclude_contact and not contact_query and payload.get(CONTACT_INDEX_KEYWORD) == 1:
                continue
            text = payload.get("text", "")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            haystack = "\n".join(lines[:6]).lower()
            if haystack and any(
                re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", haystack)
                for token in tokens
            ):
                return text
    except Exception:
        logger.exception("Heading keyword scan failed")
        return None
    return None
