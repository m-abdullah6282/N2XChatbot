from sentence_transformers import SentenceTransformer

model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global model
    if model is None:
        model = SentenceTransformer("all-MiniLM-L6-v2")
    return model

def generate_embedding(text: str) -> list[float]:
    embedding = _get_model().encode(text)
    return embedding.tolist()

def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    embeddings = _get_model().encode(texts)
    return embeddings.tolist()
