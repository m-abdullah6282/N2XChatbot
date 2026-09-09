import numpy as np
from transformers import AutoTokenizer
from onnxruntime import InferenceSession
from huggingface_hub import hf_hub_download

tokenizer = None
session = None

def _load():
    global tokenizer, session
    if tokenizer is None:
        model_path = hf_hub_download(
            "sentence-transformers/all-MiniLM-L6-v2",
            filename="onnx/model.onnx"
        )
        tokenizer = AutoTokenizer.from_pretrained(
            "sentence-transformers/all-MiniLM-L6-v2"
        )
        session = InferenceSession(model_path)

def _embed(texts: list[str]) -> list[list[float]]:
    _load()
    encoded = tokenizer(texts, padding=True, truncation=True, return_tensors="np")
    outputs = session.run(None, dict(encoded))
    embeddings = outputs[0].mean(axis=1)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return (embeddings / norms).tolist()

def generate_embedding(text: str) -> list[float]:
    return _embed([text])[0]

def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    return _embed(texts)