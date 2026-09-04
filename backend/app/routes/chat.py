import re
import time
import logging
import traceback
import threading
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Header
from groq import RateLimitError, APIStatusError

from app.models.schemas import ChatRequest
from app.services.embeddings import generate_embedding
from app.services.vector_store import search_similar_chunks, normalize_query
from app.services.llm import generate_answer, truncate_chunks
from app.db import (
    save_message,
    get_agent,
    get_session_messages,
    create_or_update_handoff,
    build_system_prompt,
    resolve_api_key,
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

RATE_LIMIT_MESSAGE = (
    "Bohat saare sawal aa rahe hain — filhal hamari service busy hai. "
    "Thodi der baad dobara try karein."
)

SESSION_RATE_LIMIT_MESSAGE = (
    "Aap ne bohat saare sawal pooch liye hain. "
    "Thodi der baad dobara try karein."
)

# ---------------------------------------------------------------------------
# Per-session rate limiter: max 50 messages per session per day (24h window).
# Uses an in-memory sliding-window counter keyed by session_id.
# ---------------------------------------------------------------------------
_MAX_MESSAGES_PER_SESSION = 50
_WINDOW_SECONDS = 24 * 60 * 60  # 24 hours

_session_counts: dict[str, list[float]] = defaultdict(list)
_session_lock = threading.Lock()


def _is_session_rate_limited(session_id: str) -> bool:
    """Return True if the session has exceeded the daily message limit."""
    if not session_id:
        return False
    now = time.time()
    cutoff = now - _WINDOW_SECONDS
    with _session_lock:
        timestamps = _session_counts[session_id]
        # Prune old entries outside the window
        _session_counts[session_id] = [t for t in timestamps if t > cutoff]
        if len(_session_counts[session_id]) >= _MAX_MESSAGES_PER_SESSION:
            return True
        _session_counts[session_id].append(now)
        return False


@router.get("/chat/agent/by-api-key")
async def agent_by_api_key(x_api_key: str = Header(default="")):
    """Resolve an API key to its bound agent.

    This is a multi-chatbot system, so API keys must unambiguously identify an
    agent. A valid, active key returns its agent's public details (id, name,
    slug, greeting, color) — never internal credentials. An invalid, revoked,
    or unbound (agent_id NULL legacy) key returns a clean 401, so a key can
    never be used to reach an agent it is not attached to."""
    key = resolve_api_key(x_api_key)
    if not key or key.get("agent_id") is None:
        raise HTTPException(status_code=401, detail="Invalid or unbound API key")
    agent = get_agent(key["agent_id"])
    if not agent:
        raise HTTPException(status_code=401, detail="API key is not bound to a valid agent")
    return {
        "id": agent["id"],
        "name": agent["name"],
        "slug": agent["slug"],
        "greeting": agent.get("greeting") or "",
        "primary_color": agent.get("primary_color") or "#2563EB",
        "key_id": key["id"],
    }


def _casual_response(question: str) -> str | None:
    """Keep lightweight conversation working when the knowledge service is down."""
    normalized = re.sub(r"[^a-z0-9\s]", "", question.lower()).strip()
    words = set(normalized.split())
    greeting_words = {
        "hi", "hello", "hey", "salam", "aoa", "assalamualaikum", "good", "morning",
        "evening", "there", "bro", "yaar",
    }

    if words and words <= {"thanks", "thank", "you", "so", "much", "shukriya", "jazakallah"}:
        return "Khushi hui! Aur koi sawal ho to zaroor poochiye."
    if words and words <= {"bye", "goodbye", "allahhafiz", "khudahafiz", "ok", "okay"}:
        return "Allah Hafiz! Jab bhi zaroorat ho, hum yahan hain."
    if words and words <= greeting_words or normalized in {"kya haal hai", "how are you", "whats up"}:
        if normalized in {"hi", "hello", "hey", "good morning", "good evening"}:
            return "Hello! Main aapki kaise madad kar sakta hoon?"
        return "Hi! Main theek hoon. Aap kis cheez mein madad chahiye?"
    return None


def _generate_answer_or_fallback(question: str, context: str, system_prompt: str, fallback: str) -> tuple[str, bool]:
    """Call the LLM and return (answer, is_rate_limit).

    Returns (answer, False) on success or general failure.
    Returns (RATE_LIMIT_MESSAGE, True) when all Groq keys are exhausted.
    """
    try:
        return generate_answer(question, context, system_prompt=system_prompt), False
    except RateLimitError as exc:
        logger.error("Groq rate limit hit (all keys exhausted): %s", exc)
        return RATE_LIMIT_MESSAGE, True
    except APIStatusError as exc:
        if exc.status_code == 413:
            logger.error("Request too large for Groq (413): %s", exc)
            return fallback, False
        raise
    except RuntimeError as exc:
        if "exhausted" in str(exc).lower():
            logger.error("All Groq API keys exhausted: %s", exc)
            return RATE_LIMIT_MESSAGE, True
        logger.exception("LLM request failed")
        logger.error("LLM request failed -> %s: %s", type(exc).__name__, exc)
        traceback.print_exc()
        return fallback, False
    except Exception as exc:
        logger.exception("LLM request failed")
        logger.error("LLM request failed -> %s: %s", type(exc).__name__, exc)
        traceback.print_exc()
        return fallback, False


@router.post("/chat")
async def chat(request: ChatRequest):
    # Ids of the rows this request inserts. The widget needs the assistant
    # message id to advance its "last seen" cursor past its own answer;
    # without it a stale cursor makes polling re-render old messages.
    user_message_id: int | None = None
    if request.session_id:
        user_message_id = save_message(
            request.session_id, "user", request.question, agent_id=request.agent_id
        )

    def _reply(answer: str, sources_used: int = 0, was_fallback: int = 0):
        message_id: int | None = None
        if request.session_id:
            message_id = save_message(
                request.session_id,
                "assistant",
                answer,
                was_fallback=was_fallback,
                agent_id=request.agent_id,
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

    # Per-session rate limit: prevent a single user from draining the API quota.
    if _is_session_rate_limited(request.session_id or ""):
        logger.warning(
            "Session %s hit rate limit (%d msgs/%dh).",
            request.session_id,
            _MAX_MESSAGES_PER_SESSION,
            _WINDOW_SECONDS // 3600,
        )
        return _reply(SESSION_RATE_LIMIT_MESSAGE, was_fallback=1)

    # Hinglish/Roman-Urdu queries ("projects k naam btao") carry very little
    # English signal, so the (English-only) embedding model scores them far
    # below the vector threshold. Normalize common Hinglish filler -> English
    # keywords before embedding AND passing to the keyword-based search. This
    # also passes "tell", "names" etc. through to _heading_keyword_match, which
    # otherwise would not fire for a purely Roman-Urdu question.
    normalized_question = normalize_query(request.question)

    # 1. Embed the question
    try:
        query_embedding = generate_embedding(normalized_question)
    except Exception as exc:
        logger.exception("Embedding generation failed")
        logger.error("Embedding generation failed -> %s: %s", type(exc).__name__, exc)
        return _reply(RETRIEVAL_UNAVAILABLE_MESSAGE)

    # 2. Search Qdrant for relevant chunks (strictly the agent's own knowledge)
    relevant_chunks, retrieval_available = search_similar_chunks(
        query_embedding,
        top_k=5,
        agent_id=request.agent_id,
        query_text=normalized_question,
    )

    if not retrieval_available:
        return _reply(RETRIEVAL_UNAVAILABLE_MESSAGE)

    # 3. Soft-retry fallback: when nothing cleared the (already lowered)
    # threshold, run one more forgiving pass with a near-zero score cut so the
    # LLM at least sees the closest available content. Only if Qdrant genuinely
    # has no points for this agent does the real fallback fire.
    if not relevant_chunks:
        try:
            relevant_chunks, retrieval_available = search_similar_chunks(
                query_embedding,
                top_k=8,
                agent_id=request.agent_id,
                score_threshold=0.05,
                query_text=normalized_question,
            )
            relevant_chunks = list(relevant_chunks)
        except Exception:
            logger.exception("Soft-retry search failed")
    relevant_chunks = list(relevant_chunks)

    # 4. Combine only retrieved chunks into the context, keeping the most
    # relevant (top-scoring) chunks and truncating everything beyond
    # MAX_CONTEXT_CHARS, so the request never exceeds the LLM provider's size
    # limit (oversized bodies surface as HTTP 413).
    sources_used = 0
    if relevant_chunks:
        selected = truncate_chunks(relevant_chunks)
        if selected:
            context = "\n\n".join(selected)
            sources_used = len(selected)
        else:
            context = NO_RELEVANT_CONTEXT_FOUND
    else:
        context = NO_RELEVANT_CONTEXT_FOUND

    # 5. Build the agent's system prompt: the stored prompt is already the
    # resolved one (the Advanced custom override when present, otherwise the
    # universal template filled with name/description). Fall back to a fresh
    # template build only if nothing is stored.
    system_prompt = DEFAULT_SYSTEM_PROMPT
    if request.agent_id is not None:
        agent = get_agent(request.agent_id)
        if agent:
            system_prompt = agent["system_prompt"] or build_system_prompt(
                agent["name"], agent.get("description") or ""
            )

    # 6. Ask LLM (only when there is retrieval context to answer from). When
    # no relevant chunks were found the bot must clearly say the info is not
    # available in the knowledge base instead of improvising or asking for
    # contact details, so the fallback message is returned directly and a
    # human handoff is created. This also keeps per-agent custom prompts from
    # overriding the KB-limitation behavior.
    if context == NO_RELEVANT_CONTEXT_FOUND:
        return _reply(FALLBACK_MESSAGE, sources_used=0, was_fallback=1)

    answer, is_rate_limit = _generate_answer_or_fallback(
        request.question, context, system_prompt, RETRIEVAL_UNAVAILABLE_MESSAGE
    )

    was_fallback = 1 if is_rate_limit or answer == FALLBACK_MESSAGE else 0
    return _reply(answer, sources_used=sources_used, was_fallback=was_fallback)


@router.get("/chat/messages/{session_id}")
async def session_messages(session_id: str):
    """Lightweight public endpoint the widget polls to pick up new
    (e.g. human-agent) assistant messages for its own session."""
    return get_session_messages(session_id)
