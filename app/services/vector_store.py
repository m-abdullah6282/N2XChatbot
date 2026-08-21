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

def store_chunks(chunks: list[str], embeddings: list[list[float]], filename: str, agent_id: int | None = None):
    points = []
    for chunk, embedding in zip(chunks, embeddings):
        payload = {"text": chunk, "filename": filename}
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

def search_similar_chunks(query_embedding: list[float], top_k: int = 3, agent_id: int | None = None, score_threshold: float = 0.15, query_text: str | None = None) -> tuple[list[str], bool]:
    """Return matching chunks and whether Qdrant was reachable.

    The embedding model is English-only, so Roman Urdu queries score poorly
    against English sections. ``query_text`` enables a lightweight heading
    keyword boost: if the query contains a word that exactly matches a chunk's
    heading (first line), that chunk is prepended even when its vector score
    is low.
    """
    query_filter = None
    if agent_id is not None:
        query_filter = Filter(
            should=[
                IsEmptyCondition(is_empty=PayloadField(key="agent_id")),
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
            ]
        )
    else:
        # Shared (non-agent) chats should only see shared knowledge chunks.
        query_filter = Filter(
            must=[IsEmptyCondition(is_empty=PayloadField(key="agent_id"))]
        )
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

    chunks = [result.payload["text"] for result in results]

    if query_text:
        heading_match = _heading_keyword_match(query_text, query_filter)
        if heading_match and heading_match not in chunks:
            chunks.insert(0, heading_match)
            chunks = chunks[: top_k + 1]

    return chunks, True


def _heading_keyword_match(query_text: str, query_filter: Filter | None) -> str | None:
    """Return the first chunk whose heading or leading content matches a
    significant query word.

    A "significant" word is 3+ alphanumeric characters; the match is
    case-insensitive against the chunk's heading and first few content lines
    (headings only were too strict for facts like ``20+ Clients`` that live in
    the body of a section).
    """
    tokens = {
        token
        for token in re.findall(r"[a-zA-Z0-9]+", query_text.lower())
        if len(token) >= 3
    }
    if not tokens:
        return None
    try:
        result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=query_filter,
            limit=1000,
            with_payload=True,
        )
        for point in result[0]:
            text = (point.payload or {}).get("text", "")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            haystack = "\n".join(lines[:6]).lower()
            if haystack and any(token in haystack for token in tokens):
                return text
    except Exception:
        logger.exception("Heading keyword scan failed")
        return None
    return None
