from sentence_transformers import SentenceTransformer

model = None

def _get_model():
    global model
    if model is None:
        model = SentenceTransformer("all-MiniLM-L6-v2")
    return model

def generate_embedding(text: str) -> list[float]:
    return _get_model().encode(text).tolist()

def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    return _get_model().encode(texts).tolist()