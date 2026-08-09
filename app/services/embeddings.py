from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

def generate_embedding(text: str) -> list[float]:
    embedding = model.encode(text)
    return embedding.tolist()

def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    embeddings = model.encode(texts)
    return embeddings.tolist()