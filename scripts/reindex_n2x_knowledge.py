"""Re-index the N2X knowledge document(s) with section-aware chunks.

Re-indexes both the shared copy (agent_id=None) and any agent-scoped copy
found under ``uploaded_files/agent_<id>/``.

Run from the repository root:
    .\venv\Scripts\python.exe scripts\reindex_n2x_knowledge.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    shared = Path("uploaded_files/n2x_knowledge.txt")
    if shared.exists():
        _reindex(shared, None)

    for agent_dir in Path("uploaded_files").glob("agent_*/"):
        agent_id = int(agent_dir.name.split("_", 1)[1])
        for path in agent_dir.glob("n2x_knowledge.txt"):
            _reindex(path, agent_id)


if __name__ == "__main__":
    main()
