from fastapi import APIRouter

from app.models.schemas import ChatRequest
from app.services.embeddings import generate_embedding
from app.services.vector_store import search_similar_chunks
from app.services.llm import generate_answer
from app.db import save_message

router = APIRouter()


@router.post("/chat")
async def chat(request: ChatRequest):
    if request.session_id:
        save_message(request.session_id, "user", request.question)

    # 1. Embed the question
    query_embedding = generate_embedding(request.question)

    # 2. Search Qdrant for relevant chunks
    relevant_chunks = search_similar_chunks(query_embedding, top_k=3)

    # 3. Combine chunks into context
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
