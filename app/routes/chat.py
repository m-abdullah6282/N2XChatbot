import re
import logging
import traceback

from fastapi import APIRouter

from app.models.schemas import ChatRequest
from app.services.embeddings import generate_embedding
from app.services.vector_store import search_similar_chunks
from app.services.llm import generate_answer
from app.db import (
    save_message,
    get_agent,
    get_session_messages,
    create_or_update_handoff,
    DEFAULT_SYSTEM_PROMPT,
    FALLBACK_MESSAGE,
    NO_RELEVANT_CONTEXT_FOUND,
)

router = APIRouter()
logger = logging.getLogger(__name__)

RETRIEVAL_UNAVAILABLE_MESSAGE = (
    "Hamari knowledge service filhal available nahi hai. "
    "Aap N2X System se info@n2xsystem.com ya +92 323 452 9766 par rabta kar sakte hain."
)


def _casual_response(question: str) -> str | None:
    """Keep lightweight conversation working when the knowledge service is down."""
    normalized = re.sub(r"[^a-z0-9\s]", "", question.lower()).strip()
    words = set(normalized.split())
    greeting_words = {
        "hi", "hello", "hey", "salam", "aoa", "assalamualaikum", "good", "morning",
        "evening", "there", "bro", "yaar",
    }

    if words and words <= {"thanks", "thank", "you", "so", "much", "shukriya", "jazakallah"}:
        return "Khushi hui! Aap ko N2X System ke bare mein koi bhi sawal ho to pooch sakte hain."
    if words and words <= {"bye", "goodbye", "allahhafiz", "khudahafiz", "ok", "okay"}:
        return "Allah Hafiz! Jab bhi zaroorat ho, hum yahan hain."
    if words and words <= greeting_words or normalized in {"kya haal hai", "how are you", "whats up"}:
        if normalized in {"hi", "hello", "hey", "good morning", "good evening"}:
            return "Hello! How can I help you with N2X System today?"
        return "Hi! Main theek hoon. N2X System ke bare mein aap ko kis cheez mein madad chahiye?"
    return None


def _generate_answer_or_fallback(question: str, context: str, fallback: str) -> str:
    try:
        return generate_answer(question, context)
    except Exception as exc:
        logger.exception("LLM request failed")
        logger.error("LLM request failed -> %s: %s", type(exc).__name__, exc)
        traceback.print_exc()
        return fallback


@router.post("/chat")
async def chat(request: ChatRequest):
    # Ids of the rows this request inserts. The widget needs the assistant
    # message id to advance its "last seen" cursor past its own answer;
    # without it a stale cursor makes polling re-render old messages.
    user_message_id: int | None = None
    if request.session_id:
        user_message_id = save_message(request.session_id, "user", request.question)

    def _reply(answer: str, sources_used: int = 0, was_fallback: int = 0):
        message_id: int | None = None
        if request.session_id:
            message_id = save_message(
                request.session_id, "assistant", answer, was_fallback=was_fallback
            )
            if was_fallback:
                create_or_update_handoff(request.session_id, request.question, request.agent_id)
        return {
            "question": request.question,
            "answer": answer,
            "sources_used": sources_used,
            "user_message_id": user_message_id,
            "message_id": message_id,
        }

    casual_answer = _casual_response(request.question)
    if casual_answer is not None:
        return _reply(casual_answer)

    # 1. Embed the question
    try:
        query_embedding = generate_embedding(request.question)
    except Exception as exc:
        logger.exception("Embedding generation failed")
        logger.error("Embedding generation failed -> %s: %s", type(exc).__name__, exc)
        return _reply(RETRIEVAL_UNAVAILABLE_MESSAGE)

    # 2. Search Qdrant for relevant chunks (agent-specific + shared)
    relevant_chunks, retrieval_available = search_similar_chunks(
        query_embedding,
        top_k=3,
        agent_id=request.agent_id,
        query_text=request.question,
    )

    if not retrieval_available:
        return _reply(RETRIEVAL_UNAVAILABLE_MESSAGE)

    # 3. Combine only retrieved chunks into the context.
    relevant_chunks = list(relevant_chunks)

    sources_used = 0
    if relevant_chunks:
        context = "\n\n".join(relevant_chunks)
        sources_used = len(relevant_chunks)
    else:
        context = NO_RELEVANT_CONTEXT_FOUND

    # 4. Use the selected agent's system prompt (if any), else the default
    system_prompt = DEFAULT_SYSTEM_PROMPT
    if request.agent_id is not None:
        agent = get_agent(request.agent_id)
        if agent:
            system_prompt = agent["system_prompt"]

    # 5. Ask LLM
    answer = _generate_answer_or_fallback(
        request.question, context, RETRIEVAL_UNAVAILABLE_MESSAGE
    )

    was_fallback = 1 if answer == FALLBACK_MESSAGE else 0
    return _reply(answer, sources_used=sources_used, was_fallback=was_fallback)


@router.get("/chat/messages/{session_id}")
async def session_messages(session_id: str):
    """Lightweight public endpoint the widget polls to pick up new
    (e.g. human-agent) assistant messages for its own session."""
    return get_session_messages(session_id)
