import os
import re
import time
import uuid
import logging
import traceback
import threading
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Header
from groq import RateLimitError, APIStatusError

from app.models.schemas import ChatRequest, KeyChatRequest
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

LLM_UNAVAILABLE_MESSAGE = (
    "Mujhe filhal jawaab tayyar karne mein dikkat aa rahi hai. "
    "Aap N2X System se info@n2xsystem.com ya +92 323 452 9766 par rabta kar sakte hain."
)

RATE_LIMIT_MESSAGE = (
    "Bohat saare sawal aa rahe hain - filhal hamari service busy hai. "
    "Thodi der baad dobara try karein."
)

SESSION_RATE_LIMIT_MESSAGE = (
    "Aap ne bohat saare sawal pooch liye hain. "
    "Thodi der baad dobara try karein."
)

# ---------------------------------------------------------------------------
# Per-session rate limiter: max 50 messages per session per day (24h window).
# In-memory sliding window keyed by session_id (resets on restart).
# ---------------------------------------------------------------------------
_MAX_MESSAGES_PER_SESSION = 50
_WINDOW_SECONDS = 24 * 60 * 60

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
        _session_counts[session_id] = [t for t in timestamps if t > cutoff]
        if len(_session_counts[session_id]) >= _MAX_MESSAGES_PER_SESSION:
            return True
        _session_counts[session_id].append(now)
        return False


# ---------------------------------------------------------------------------
# Per-API-KEY rate limiter (protects the owner's Groq quota from one leaked or
# abused key). Two windows: per minute and per day. In-memory, like the session
# limiter. Tune via env vars without code changes.
# ---------------------------------------------------------------------------
_KEY_LIMIT_PER_MINUTE = int(os.getenv("API_KEY_RATE_LIMIT_PER_MINUTE", "30"))
_KEY_LIMIT_PER_DAY = int(os.getenv("API_KEY_RATE_LIMIT_PER_DAY", "2000"))
_KEY_MINUTE_WINDOW = 60
_KEY_DAY_WINDOW = 24 * 60 * 60

_key_hits: dict[int, list[float]] = defaultdict(list)
_key_lock = threading.Lock()


def _check_key_rate_limit(key_id: int) -> None:
    """Raise HTTP 429 (with Retry-After) when this key exceeded its limits."""
    now = time.time()
    retry_after = 0
    with _key_lock:
        hits = [t for t in _key_hits[key_id] if t > now - _KEY_DAY_WINDOW]
        recent = [t for t in hits if t > now - _KEY_MINUTE_WINDOW]
        if len(recent) >= _KEY_LIMIT_PER_MINUTE:
            retry_after = int(_KEY_MINUTE_WINDOW - (now - recent[0])) + 1
        elif len(hits) >= _KEY_LIMIT_PER_DAY:
            retry_after = int(_KEY_DAY_WINDOW - (now - hits[0])) + 1
        else:
            hits.append(now)
        _key_hits[key_id] = hits
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many requests for this API key. Please slow down.",
            headers={"Retry-After": str(retry_after)},
        )


# ---------------------------------------------------------------------------
# API-key session namespacing.
# A client-chosen session id is stored as "api<agent_id>:<client_id>", so:
#   - the same client id used with two different agents never collides,
#   - a session created through a key can never be read through another
#     agent's key,
#   - the public (unauthenticated) endpoints refuse ids containing ":".
# ---------------------------------------------------------------------------
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")


def _api_session(agent_id: int, client_session_id: str) -> str:
    return f"api{agent_id}:{client_session_id}"


def _authenticate_key(raw_key: str) -> tuple[dict, dict]:
    """Return (key_row, agent_row) for a valid, active, agent-bound key.
    Anything else is a clean 401 (never reveals which part was wrong)."""
    key = resolve_api_key((raw_key or "").strip())
    if not key or key.get("agent_id") is None:
        raise HTTPException(status_code=401, detail="Invalid, revoked or unbound API key")
    agent = get_agent(key["agent_id"])
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid, revoked or unbound API key")
    return key, agent


@router.get("/chat/agent/by-api-key")
async def agent_by_api_key(x_api_key: str = Header(default="")):
    """Resolve an API key to its bound agent's PUBLIC details only."""
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
    """Call the LLM and return (answer, is_rate_limit)."""
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


def _run_chat(question: str, session_id: str | None, agent_id: int | None) -> dict:
    """The ONE chat pipeline shared by the public /chat route and the API-key
    /v1/chat route. Plain `def` on purpose: embedding, Qdrant, Groq and SQLite
    are blocking, so FastAPI runs sync endpoints in its threadpool instead of
    freezing the event loop."""
    user_message_id: int | None = None
    if session_id:
        user_message_id = save_message(session_id, "user", question, agent_id=agent_id)

    def _reply(answer: str, sources_used: int = 0, was_fallback: int = 0):
        message_id: int | None = None
        if session_id:
            message_id = save_message(
                session_id,
                "assistant",
                answer,
                was_fallback=was_fallback,
                agent_id=agent_id,
            )
            if was_fallback:
                create_or_update_handoff(session_id, question, agent_id)
        return {
            "question": question,
            "answer": answer,
            "sources_used": sources_used,
            "user_message_id": user_message_id,
            "message_id": message_id,
            "was_fallback": bool(was_fallback),
        }

    casual_answer = _casual_response(question)
    if casual_answer is not None:
        return _reply(casual_answer)

    # Per-session rate limit: prevent a single user from draining the API quota.
    if _is_session_rate_limited(session_id or ""):
        logger.warning(
            "Session %s hit rate limit (%d msgs/%dh).",
            session_id,
            _MAX_MESSAGES_PER_SESSION,
            _WINDOW_SECONDS // 3600,
        )
        return _reply(SESSION_RATE_LIMIT_MESSAGE, was_fallback=1)

    # Hinglish/Roman-Urdu queries carry little English signal, so normalize
    # common filler -> English keywords before embedding and keyword search.
    normalized_question = normalize_query(question)

    # 1. Embed the question
    try:
        query_embedding = generate_embedding(normalized_question)
    except Exception as exc:
        logger.exception("Embedding generation failed")
        logger.error("Embedding generation failed -> %s: %s", type(exc).__name__, exc)
        return _reply(RETRIEVAL_UNAVAILABLE_MESSAGE, was_fallback=1)

    # 2. Search Qdrant (strictly this agent's own knowledge)
    relevant_chunks, retrieval_available = search_similar_chunks(
        query_embedding,
        top_k=5,
        agent_id=agent_id,
        query_text=normalized_question,
    )

    if not retrieval_available:
        return _reply(RETRIEVAL_UNAVAILABLE_MESSAGE, was_fallback=1)

    # 3. Soft-retry with a near-zero score cut if nothing cleared the threshold.
    if not relevant_chunks:
        try:
            relevant_chunks, retrieval_available = search_similar_chunks(
                query_embedding,
                top_k=8,
                agent_id=agent_id,
                score_threshold=0.05,
                query_text=normalized_question,
            )
            relevant_chunks = list(relevant_chunks)
        except Exception:
            logger.exception("Soft-retry search failed")
    relevant_chunks = list(relevant_chunks)

    # 4. Build the context, capped so the request never causes an HTTP 413.
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

    # 5. The agent's stored system prompt (custom override or filled template).
    system_prompt = DEFAULT_SYSTEM_PROMPT
    if agent_id is not None:
        agent = get_agent(agent_id)
        if agent:
            system_prompt = agent["system_prompt"] or build_system_prompt(
                agent["name"], agent.get("description") or ""
            )

    # 6. No context -> grounded fallback + human handoff, never call the LLM.
    if context == NO_RELEVANT_CONTEXT_FOUND:
        return _reply(FALLBACK_MESSAGE, sources_used=0, was_fallback=1)

    answer, is_rate_limit = _generate_answer_or_fallback(
        question, context, system_prompt, LLM_UNAVAILABLE_MESSAGE
    )

    was_fallback = (
        1
        if is_rate_limit or answer == LLM_UNAVAILABLE_MESSAGE or FALLBACK_MESSAGE in answer
        else 0
    )
    return _reply(answer, sources_used=sources_used, was_fallback=was_fallback)


# ---------------------------------------------------------------------------
# Public routes (website chat page / widget) - unchanged behaviour
# ---------------------------------------------------------------------------
@router.post("/chat")
def chat(request: ChatRequest):
    # ":" is reserved for API-key sessions (see _api_session).
    if request.session_id and ":" in request.session_id:
        raise HTTPException(status_code=400, detail="Invalid session_id")
    return _run_chat(request.question, request.session_id, request.agent_id)


@router.get("/chat/messages/{session_id}")
def session_messages(session_id: str, agent_id: int | None = None):
    """Public endpoint the widget polls to pick up human-agent replies.
    Optional ?agent_id= restricts results to that agent's messages. Sessions
    created through an API key are never readable here."""
    if ":" in session_id:
        return []
    return get_session_messages(session_id, agent_id=agent_id)


# ---------------------------------------------------------------------------
# API-key routes: the key alone decides WHICH agent answers.
# ---------------------------------------------------------------------------
@router.post("/v1/chat")
def chat_with_api_key(body: KeyChatRequest, x_api_key: str = Header(default="")):
    key, agent = _authenticate_key(x_api_key)
    _check_key_rate_limit(key["id"])

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question cannot be empty")

    client_session_id = body.session_id or uuid.uuid4().hex
    if not _SESSION_ID_RE.fullmatch(client_session_id):
        raise HTTPException(
            status_code=400,
            detail="session_id must be 8-64 characters: letters, digits, '-' or '_'",
        )

    # TODO(quota): count this message against the agent owner's plan here
    # (subscription_service.can_send_message / usage_records) once wired.

    result = _run_chat(
        question,
        _api_session(agent["id"], client_session_id),
        agent["id"],  # always from the key; any agent_id in the body is ignored
    )
    return {
        "answer": result["answer"],
        "session_id": client_session_id,
        "sources_used": result["sources_used"],
        "message_id": result["message_id"],
        "handoff_requested": result["was_fallback"],
    }


@router.get("/v1/chat/messages/{session_id}")
def api_session_messages(
    session_id: str,
    after_id: int = 0,
    x_api_key: str = Header(default=""),
):
    """Poll a conversation started through this key (e.g. to receive a human
    agent's reply). Only sessions of the key's own agent are visible."""
    _key, agent = _authenticate_key(x_api_key)
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    rows = get_session_messages(
        _api_session(agent["id"], session_id), agent_id=agent["id"]
    )
    return [
        {"id": r["id"], "role": r["role"], "content": r["content"], "created_at": r["created_at"]}
        for r in rows
        if r["id"] > after_id
    ]