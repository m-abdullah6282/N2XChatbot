from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
import shutil
import os

from app.services.pdf_processor import extract_text_from_pdf, chunk_text
from app.services.embeddings import generate_embeddings_batch
from app.services.auth import require_admin
from app.services.vector_store import create_collection_if_not_exists, delete_points_by_filename, store_chunks

router = APIRouter()
UPLOAD_DIR = "uploaded_files"
ALLOWED_EXTENSIONS = (".pdf", ".txt")


def agent_upload_dir(agent_id: int) -> str:
    return os.path.join(UPLOAD_DIR, f"agent_{agent_id}")


@router.post("/upload", dependencies=[Depends(require_admin)])
async def upload_pdf(file: UploadFile = File(...), agent_id: int | None = Form(None)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and TXT files are allowed")

    upload_dir = agent_upload_dir(agent_id) if agent_id is not None else UPLOAD_DIR
    if agent_id is not None:
        os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Extract text
    text = extract_text(file_path, ext)

    # Chunk it
    chunks = [c for c in chunk_text(text) if c.strip()]

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No text could be extracted from this file. The PDF may be scanned/image-only. Upload the content as a .txt file instead."
        )

    # Generate embeddings
    embeddings = generate_embeddings_batch(chunks)

    # Store in Qdrant, replacing any previously stored points for this file
    create_collection_if_not_exists()
    delete_points_by_filename(file.filename, agent_id)
    store_chunks(chunks, embeddings, file.filename, agent_id)

    return {
        "filename": file.filename,
        "message": "File uploaded and processed successfully",
        "chunks_created": len(chunks)
    }


def extract_text(file_path: str, ext: str) -> str:
    if ext == ".txt":
        with open(file_path, "rb") as f:
            raw = f.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")
    return extract_text_from_pdf(file_path)
