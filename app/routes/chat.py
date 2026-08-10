from fastapi import APIRouter

from app.models.schemas import ChatRequest
from app.services.embeddings import generate_embedding
from app.services.vector_store import search_similar_chunks
from app.services.llm import generate_answer
from app.db import save_message

router = APIRouter()

CONTACT_KEYWORDS = (
    "contact", "baat", "raabta", "milna", "email", "phone", "number",
    "address", "whatsapp", "call", "link", "reach", "talk",
)
CONTACT_CHUNK = (
    "N2X System CONTACT: Website: www.n2xsystem.com\n"
    "Email: info@n2xsystem.com\n"
    "Phone: +92 323 452 9766\n"
    "Address: Plot C 12, Street 195, DHA Phase 1, Lahore 54000"
)


def _is_contact_question(question: str) -> bool:
    q = question.lower()
    return any(word in q for word in CONTACT_KEYWORDS)


@router.post("/chat")
async def chat(request: ChatRequest):
    if request.session_id:
        save_message(request.session_id, "user", request.question)

    # 1. Embed the question
    query_embedding = generate_embedding(request.question)

    # 2. Search Qdrant for relevant chunks
    relevant_chunks = search_similar_chunks(query_embedding, top_k=3)

    # 3. Combine chunks into context. If the question is about
    # contact/talk ("baat kaha pr kru?"), always include contact info.
    relevant_chunks = list(relevant_chunks)
    if _is_contact_question(request.question):
        relevant_chunks.insert(0, CONTACT_CHUNK)
    context = "\n\n".join(relevant_chunks)

    # 4. Ask LLM
    answer = generate_answer(request.question, context)

    if request.session_id:
        save_message(request.session_id, "assistant", answer)

    return {
        "question": request.question,
        "answer": answer,
        "sources_used": len(relevant_chunks)
    }
