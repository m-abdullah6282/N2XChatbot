import os
import requests

HF_API_TOKEN = os.getenv("HF_API_TOKEN")
HF_API_URL = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"

HEADERS = {"Authorization": f"Bearer {HF_API_TOKEN}"}


def _call_hf(texts: list[str]) -> list[list[float]]:
    response = requests.post(
        HF_API_URL,
        headers=HEADERS,
        json={"inputs": texts, "options": {"wait_for_model": True}},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def generate_embedding(text: str) -> list[float]:
    return _call_hf([text])[0]


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    return _call_hf(texts)