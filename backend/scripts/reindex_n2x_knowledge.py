"""Re-index agent-scoped N2X knowledge document(s) with section-aware chunks.

Shared-scope uploads (agent_id=None) are no longer supported: each agent
retrieves only its own documents, so only ``uploaded_files/agent_<id>/``
copies are re-indexed here.

Run from the repository root:
    .\venv\Scripts\python.exe backend\scripts\reindex_n2x_knowledge.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))
UPLOADED_FILES_DIR = _BACKEND_DIR / "uploaded_files"

from app.services.embeddings import generate_embeddings_batch
from app.services.pdf_processor import chunk_text
from app.services.vector_store import (
    create_collection_if_not_exists,
    delete_points_by_filename,
    store_chunks,
)


def _reindex(path: Path, agent_id: int | None) -> None:
    text = path.read_text(encoding="utf-8")
    chunks = chunk_text(text)
    scope = f"agent_id={agent_id}" if agent_id is not None else "shared"
    print(f"Re-indexing {path.name} ({scope}): {len(chunks)} section-aware chunks")
    for index, chunk in enumerate(chunks, start=1):
        print(f"\n--- chunk {index} ({len(chunk)} characters) ---\n{chunk}")

    embeddings = generate_embeddings_batch(chunks)
    create_collection_if_not_exists()
    delete_points_by_filename(path.name, agent_id)
    store_chunks(chunks, embeddings, path.name, agent_id)
    print(f"\nRe-index complete for {path.name} ({scope}).")


def main() -> None:
    for agent_dir in UPLOADED_FILES_DIR.glob("agent_*/"):
        agent_id = int(agent_dir.name.split("_", 1)[1])
        for path in agent_dir.glob("n2x_knowledge.txt"):
            _reindex(path, agent_id)


if __name__ == "__main__":
    main()
