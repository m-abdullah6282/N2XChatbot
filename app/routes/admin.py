import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.db import (
    get_conversations,
    create_api_key,
    list_api_keys,
    delete_api_key,
)
from app.models.schemas import ApiKeyCreate
from app.services.auth import (
    COOKIE_NAME,
    create_session,
    destroy_session,
    is_authenticated,
    require_admin,
)
from app.services.vector_store import delete_points_by_filename

router = APIRouter()
UPLOAD_DIR = "uploaded_files"
ALLOWED_EXTENSIONS = (".pdf", ".txt")


class LoginRequest(BaseModel):
    username: str
    password: str


def _safe_filename(filename: str) -> bool:
    if os.path.basename(filename) != filename:
        return False
    return filename.lower().endswith(ALLOWED_EXTENSIONS)


@router.post("/admin/login")
def login(req: LoginRequest, response: Response):
    token = create_session(req.username, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="lax",
    )
    return {"message": "Login successful"}


@router.post("/admin/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        destroy_session(token)
    response.delete_cookie(key=COOKIE_NAME)
    return {"message": "Logged out"}


@router.get("/admin/check")
def check_auth(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    return {"authenticated": is_authenticated(token)}


@router.get("/documents", dependencies=[Depends(require_admin)])
def list_documents():
    files = []
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(path) and name.lower().endswith(ALLOWED_EXTENSIONS):
            files.append({"filename": name, "size": os.path.getsize(path)})
    return files


@router.delete("/documents/{filename}", dependencies=[Depends(require_admin)])
def delete_document(filename: str):
    if not _safe_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(path):
        os.remove(path)

    delete_points_by_filename(filename)
    return {"filename": filename, "message": "Document deleted"}


@router.get("/conversations", dependencies=[Depends(require_admin)])
def conversations():
    return get_conversations()


@router.post("/api-keys", dependencies=[Depends(require_admin)])
def create_key(req: ApiKeyCreate):
    api_key = create_api_key(req.label)
    return {"api_key": api_key, "label": req.label, "message": "API key created"}


@router.get("/api-keys", dependencies=[Depends(require_admin)])
def list_keys():
    return list_api_keys()


@router.delete("/api-keys/{key_id}", dependencies=[Depends(require_admin)])
def delete_key(key_id: int):
    if not delete_api_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"message": "API key deleted"}
