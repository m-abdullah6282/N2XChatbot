"""Inspect or explicitly wipe the Qdrant knowledge_base collection.

Run from the repository root:
    .\venv\Scripts\python.exe scripts\qdrant_knowledge_base.py
    .\venv\Scripts\python.exe scripts\qdrant_knowledge_base.py --full-text
    .\venv\Scripts\python.exe scripts\qdrant_knowledge_base.py --wipe --confirm-wipe
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FilterSelector

from app.config import QDRANT_API_KEY, QDRANT_URL

COLLECTION_NAME = "knowledge_base"


def get_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


def inventory(client: QdrantClient, full_text: bool) -> int:
    offset = None
    filenames: Counter[str] = Counter()
    total = 0

    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            filename = str(payload.get("filename", "<missing filename>"))
            text = str(payload.get("text", ""))
            filenames[filename] += 1
            total += 1
            snippet = text if full_text else text.replace("\n", " ")[:240]
            print(f"id={point.id} | filename={filename} | text={snippet}")

        if offset is None:
            break

    print("\nFilename inventory:")
    if not filenames:
        print("  (collection is empty)")
    for filename, count in sorted(filenames.items()):
        print(f"  {filename}: {count} chunks")
    print(f"\nTotal points: {total}")
    return total


def wipe(client: QdrantClient) -> None:
    # An empty filter matches every point while retaining the collection schema.
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(filter=Filter(must=[])),
        wait=True,
    )
    remaining = client.count(collection_name=COLLECTION_NAME, exact=True).count
    print(f"Collection wipe complete. Remaining points: {remaining}")
    if remaining != 0:
        raise RuntimeError("Wipe did not remove every point")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or wipe the Qdrant knowledge_base collection.")
    parser.add_argument("--full-text", action="store_true", help="Print full chunk text instead of snippets.")
    parser.add_argument("--wipe", action="store_true", help="Delete every point in knowledge_base.")
    parser.add_argument(
        "--confirm-wipe",
        action="store_true",
        help="Required together with --wipe to prevent accidental deletion.",
    )
    args = parser.parse_args()

    if args.wipe and not args.confirm_wipe:
        parser.error("--wipe requires --confirm-wipe")
    if args.confirm_wipe and not args.wipe:
        parser.error("--confirm-wipe must be used with --wipe")

    try:
        client = get_client()
        if args.wipe:
            wipe(client)
        else:
            inventory(client, args.full_text)
    except Exception as exc:
        print(f"Qdrant operation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
