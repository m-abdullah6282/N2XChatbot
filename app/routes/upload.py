from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Request
import shutil
import os

from app.services import pdf_processor
from app.services.embeddings import generate_embeddings_batch
from app.services.auth import ensure_agent_access, get_current_admin, require_admin
from app.services.vector_store import create_collection_if_not_exists, delete_points_by_filename, store_chunks

router = APIRouter()
UPLOAD_DIR = "uploaded_files"
ALLOWED_EXTENSIONS = (".pdf", ".txt")
TEXT_EXTRACTION_MIN_CHARS = 40

NO_TEXT_EXTRACTED_MESSAGE = (
    "Is file se koi text nahi mila - ye scanned/image-based PDF ho sakti hai "
    "jisme sirf images hain. Text version (.txt) bana kar upload karein, ya OCR "
    "enable karne ke liye Tesseract aur Poppler install karein."
)


def agent_upload_dir(agent_id: int) -> str:
    return os.path.join(UPLOAD_DIR, f"agent_{agent_id}")


@router.post("/upload", dependencies=[Depends(require_admin)])
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    agent_id: int | None = Form(None),
):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and TXT files are allowed")

    admin_id, role = get_current_admin(request)
    ensure_agent_access(agent_id, admin_id, role)

    upload_dir = agent_upload_dir(agent_id) if agent_id is not None else UPLOAD_DIR
    if agent_id is not None:
        os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Extract text, falling back to OCR for scanned/image-only PDFs. A file
    # that yields nothing (or a PDF that fails to parse at all) gets a clear
    # user-facing error instead of a raw 500.
    text, ocr_used = try_extract_text(file_path, ext)

    # Chunk it
    chunks = [c for c in pdf_processor.chunk_text(text) if c.strip()]

    if not chunks:
        raise HTTPException(status_code=400, detail=NO_TEXT_EXTRACTED_MESSAGE)

    # Generate embeddings
    embeddings = generate_embeddings_batch(chunks)

    # Store in Qdrant, replacing any previously stored points for this file
    create_collection_if_not_exists()
    delete_points_by_filename(file.filename, agent_id)
    store_chunks(chunks, embeddings, file.filename, agent_id)

    return {
        "filename": file.filename,
        "message": "File uploaded and processed successfully",
        "chunks_created": len(chunks),
        "ocr_used": ocr_used,
    }


def extract_text(file_path: str, ext: str) -> str:
    if ext == ".txt":
        with open(file_path, "rb") as f:
            raw = f.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")
    return pdf_processor.extract_text_from_pdf(file_path)


def try_extract_text(file_path: str, ext: str) -> tuple[str, bool]:
    """Return (text, ocr_used).

    For PDFs, plain text extraction is tried first; if it yields too little
    text (a scanned/image-based PDF) or throws, an OCR pass runs. Both failing
    results in an empty string so the caller can report the graceful error."""
    if ext != ".pdf":
        return extract_text(file_path, ext), False
    text = ""
    try:
        text = extract_text(file_path, ext) or ""
    except Exception:
        text = ""
    if len(text.strip()) < TEXT_EXTRACTION_MIN_CHARS:
        ocr_text = pdf_processor.extract_text_from_pdf_ocr(file_path)
        if len(ocr_text.strip()) >= TEXT_EXTRACTION_MIN_CHARS:
            return ocr_text, True
    return text, False
