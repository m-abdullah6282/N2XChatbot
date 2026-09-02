from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Request
import shutil
import os

from app.services import pdf_processor
from app.services.embeddings import generate_embeddings_batch
from app.services.auth import ensure_agent_access, get_current_admin, require_admin
from app.services.vector_store import create_collection_if_not_exists, delete_points_by_filename, store_chunks
from app.services.subscription_service import enforce_document_limit, SubscriptionError
from app.db import (
    create_document,
    update_document_status,
    set_document_file_size,
    get_agent,
    list_documents,
    delete_document_record_by_scope,
)

router = APIRouter()
UPLOAD_DIR = "uploaded_files"
ALLOWED_EXTENSIONS = (".pdf", ".txt")

NO_TEXT_EXTRACTED_MESSAGE = (
    "Is file se koi text extract nahi ho saka. Agar ye scanned/image-based PDF hai "
    "to OCR support nahi hai. Please text-based PDF upload karein ya file ko .txt "
    "mein convert karke upload karein."
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

    # Ownership: a normal admin may only upload to agents they own (or to the
    # shared scope). ensure_agent_access enforces this server-side.
    ensure_agent_access(agent_id, admin_id, role)

    # Derive the document's owner, never trusting the frontend:
    # - agent-scoped uploads belong to the agent's owner.
    # - shared (agent_id=NULL) uploads belong to the authenticated uploader.
    owner_admin_id = admin_id
    if agent_id is not None:
        agent = get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        owner_admin_id = agent.get("owner_admin_id") or admin_id

    # Enforce the document plan-limit for normal admins (super admins exempt).
    if role != "super_admin":
        try:
            enforce_document_limit(admin_id, role)
        except SubscriptionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

    upload_dir = agent_upload_dir(agent_id) if agent_id is not None else UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)

    file_path_in_scope = (
        os.path.join(agent_upload_dir(agent_id), file.filename)
        if agent_id is not None
        else file.filename
    )
    file_path = os.path.join(upload_dir, file.filename)

    # Create a document record first (status = processing). On any failure we
    # mark it failed so we never falsely report 'ready'. Re-uploading the same
    # filename replaces the previous record (mirrors the Qdrant replace below).
    delete_document_record_by_scope(agent_id, file.filename)
    document_id = create_document(
        agent_id,
        owner_admin_id,
        file.filename,
        file.filename,
        file_path=file_path_in_scope,
        file_size=0,
    )

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        set_document_file_size(document_id, os.path.getsize(file_path))

        # Extract text from the file. For scanned/image-only PDFs pypdf yields
        # little or no text — the caller receives a clear error message.
        text = try_extract_text(file_path, ext)

        # Chunk it
        chunks = [c for c in pdf_processor.chunk_text(text) if c.strip()]

        if not chunks:
            update_document_status(document_id, "failed")
            raise HTTPException(status_code=400, detail=NO_TEXT_EXTRACTED_MESSAGE)

        # Generate embeddings
        embeddings = generate_embeddings_batch(chunks)

        # Store in Qdrant, replacing any previously stored points for this file.
        # Keeps existing agent_id isolation and shared-knowledge behaviour.
        create_collection_if_not_exists()
        delete_points_by_filename(file.filename, agent_id)
        store_chunks(
            chunks,
            embeddings,
            file.filename,
            agent_id,
            document_id=document_id,
            owner_admin_id=owner_admin_id,
        )

        # Reflect the real chunk count for the document record.
        update_document_status(document_id, "ready", chunks_count=len(chunks))

        return {
            "filename": file.filename,
            "message": "File uploaded and processed successfully",
            "chunks_created": len(chunks),
            "document_id": document_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        # A processing failure must never falsely show 'ready'. Keep the error
        # message safe (no internal exception details exposed to the client).
        update_document_status(document_id, "failed")
        raise HTTPException(status_code=500, detail="File processing failed")


def extract_text(file_path: str, ext: str) -> str:
    if ext == ".txt":
        with open(file_path, "rb") as f:
            raw = f.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")
    return pdf_processor.extract_text_from_pdf(file_path)


def try_extract_text(file_path: str, ext: str) -> str:
    """Extract text from an uploaded file.

    For .txt files the raw bytes are decoded. For PDFs the embedded text layer
    is read via pypdf; scanned/image-only PDFs carry no text layer and so return
    an empty string, which the caller reports with a clear "OCR not supported"
    style error message."""
    if ext != ".pdf":
        return extract_text(file_path, ext)
    try:
        return extract_text(file_path, ext) or ""
    except Exception:
        return ""


@router.get("/documents", dependencies=[Depends(require_admin)])
def list_documents_endpoint(request: Request, agent_id: int | None = None):
    admin_id, role = get_current_admin(request)
    ensure_agent_access(agent_id, admin_id, role)
    base_dir = agent_upload_dir(agent_id) if agent_id is not None else UPLOAD_DIR
    if not os.path.isdir(base_dir):
        return []
    files = []
    for name in os.listdir(base_dir):
        path = os.path.join(base_dir, name)
        if os.path.isfile(path) and name.lower().endswith(ALLOWED_EXTENSIONS):
            files.append({"filename": name, "size": os.path.getsize(path)})
    # Enrich each file with its relational document metadata when a record
    # exists, so the admin UI can show status without breaking file listing.
    if files:
        scope = "agent" if agent_id is not None else "shared"
        records = list_documents(scope=scope, agent_id=agent_id, admin_id=admin_id, role=role)
        by_name = {r["filename"]: r for r in records}
        for f in files:
            rec = by_name.get(f["filename"])
            if rec:
                f["document_id"] = rec["id"]
                f["status"] = rec["status"]
                f["chunks_count"] = rec["chunks_count"]
    return files


@router.delete("/documents/{filename}", dependencies=[Depends(require_admin)])
def delete_document(filename: str, request: Request, agent_id: int | None = None):
    if os.path.basename(filename) != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Invalid filename")

    admin_id, role = get_current_admin(request)
    ensure_agent_access(agent_id, admin_id, role)

    base_dir = agent_upload_dir(agent_id) if agent_id is not None else UPLOAD_DIR
    path = os.path.join(base_dir, filename)
    if os.path.exists(path):
        os.remove(path)

    delete_points_by_filename(filename, agent_id)
    delete_document_record_by_scope(agent_id, filename)
    return {"filename": filename, "message": "Document deleted"}
