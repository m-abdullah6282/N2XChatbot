from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition,
    MatchValue, FilterSelector, PayloadSchemaType, IsNullCondition, PayloadField,
)
import uuid
from app.config import QDRANT_URL, QDRANT_API_KEY
 
client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

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
        conditions.append(IsNullCondition(is_null=PayloadField(key="agent_id")))
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

def search_similar_chunks(query_embedding: list[float], top_k: int = 3, agent_id: int | None = None) -> list[str]:
    query_filter = None
    if agent_id is not None:
        query_filter = Filter(
            should=[
                IsNullCondition(is_null=PayloadField(key="agent_id")),
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
            ]
        )
    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_embedding,
        limit=top_k,
        query_filter=query_filter,
    )
    return [result.payload["text"] for result in results]