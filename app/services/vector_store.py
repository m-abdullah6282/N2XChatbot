from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition,
    MatchValue, FilterSelector, PayloadSchemaType,
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

def ensure_filename_index():
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="filename",
        field_schema=PayloadSchemaType.KEYWORD,
    )

def store_chunks(chunks: list[str], embeddings: list[list[float]], filename: str):
    points = []
    for chunk, embedding in zip(chunks, embeddings):
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={"text": chunk, "filename": filename}
        )
        points.append(point)

    client.upsert(collection_name=COLLECTION_NAME, points=points)

def delete_points_by_filename(filename: str):
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(
                must=[FieldCondition(key="filename", match=MatchValue(value=filename))]
            )
        ),
    )

def search_similar_chunks(query_embedding: list[float], top_k: int = 3) -> list[str]:
    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_embedding,
        limit=top_k
    )
    return [result.payload["text"] for result in results]