"""Print raw Qdrant retrieval results for the N2X knowledge-base queries.

Run from the repository root:
    .\venv\Scripts\python.exe scripts\debug_retrieval.py

This intentionally does *not* set ``score_threshold``. It is a temporary
diagnostic for seeing which chunks Qdrant would otherwise return.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Avoid an unnecessary Hugging Face metadata check when the model is already
# cached locally. This affects only the diagnostic process.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.services.embeddings import generate_embedding
from app.services.vector_store import COLLECTION_NAME, client


QUERIES = (
    "Aap ki services kya hain?",
    "Hospital Management System mein kya features hain?",
    "N2X kitne saal se kaam kar raha hai?",
)


def main() -> None:
    for query in QUERIES:
        print(f"\n{'=' * 80}\nQUERY: {query}\n{'=' * 80}")
        query_embedding = generate_embedding(query)
        print(f"Embedding dimensions: {len(query_embedding)}")

        # Deliberately omit score_threshold to inspect the raw top 10.
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            limit=10,
            with_payload=True,
        )
        for index, result in enumerate(results, start=1):
            payload = result.payload or {}
            print(f"\n#{index} score={result.score:.6f} filename={payload.get('filename', '<missing>')}")
            print("--- chunk text ---")
            print(payload.get("text", "<missing text>"))
            print("--- end chunk text ---")


if __name__ == "__main__":
    main()
