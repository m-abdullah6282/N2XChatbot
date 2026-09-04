import time
import logging
import threading
from groq import Groq, RateLimitError, APIConnectionError, APITimeoutError, APIStatusError
from app.config import GROQ_API_KEYS
from app.db import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

# Multi-key rotation: maintain a list of Groq clients, one per API key.
# When a key hits the daily (TPD) rate limit, it is marked exhausted and
# the next available key is tried. If all keys are exhausted, the request
# fails with a clear error.
_clients: list[Groq] = [Groq(api_key=k) for k in GROQ_API_KEYS] if GROQ_API_KEYS else []
_key_exhausted: list[bool] = [False] * len(_clients)
_lock = threading.Lock()
_current_idx = 0


def _get_next_client() -> Groq | None:
    """Return the next available Groq client, rotating past exhausted keys.
    Returns None if all keys are exhausted."""
    global _current_idx
    if not _clients:
        return None
    with _lock:
        start = _current_idx
        for _ in range(len(_clients)):
            if not _key_exhausted[_current_idx]:
                client = _clients[_current_idx]
                _current_idx = (_current_idx + 1) % len(_clients)
                return client
            _current_idx = (_current_idx + 1) % len(_clients)
    return None


def _mark_key_exhausted(client: Groq):
    """Mark a client's key as daily-limit-exhausted so future calls skip it."""
    with _lock:
        for i, c in enumerate(_clients):
            if c is client:
                _key_exhausted[i] = True
                logger.warning("API key #%d marked as daily-limit-exhausted.", i)
                break


def _reset_exhausted_keys():
    """Reset all exhausted keys (call periodically or on next day)."""
    with _lock:
        exhausted_count = sum(_key_exhausted)
        for i in range(len(_key_exhausted)):
            _key_exhausted[i] = False
        if exhausted_count:
            logger.info(
                "Reset %d previously exhausted Groq API key(s).", exhausted_count
            )


def get_key_status() -> dict:
    """Return the current status of all API keys for diagnostics."""
    with _lock:
        return {
            "total_keys": len(_clients),
            "exhausted_keys": sum(_key_exhausted),
            "available_keys": len(_clients) - sum(_key_exhausted),
            "key_details": [
                {"index": i, "exhausted": _key_exhausted[i]}
                for i in range(len(_clients))
            ],
        }

# groq/compound-mini exposes a 131,072-token context window (~500KB of text).
# We deliberately cap the retrieved context far below that: answers are 2-4
# sentences so a handful of chunks is plenty, and staying well under the window
# also keeps the HTTP request body below Groq's entity-size cap (oversized
# bodies surface as HTTP 413 "Request Entity Too Large").
MAX_CONTEXT_CHARS = 8_000
MAX_SYSTEM_PROMPT_CHARS = 4_000


def truncate_chunks(chunks: list[dict], max_chars: int = MAX_CONTEXT_CHARS) -> list[str]:
    """Keep the most relevant chunks for the LLM context, dropping or trimming
    anything beyond ``max_chars``.

    ``chunks`` is a list of ``{"text": str, "score": float}`` dicts. Greedy
    selection sorts highest-scoring chunks first: full chunks are kept while
    they fit, the first chunk that would overflow is sliced to the remaining
    budget, and lower-scoring chunks are dropped entirely.
    """
    if max_chars <= 0:
        return []
    budget = max_chars
    selected: list[str] = []
    for chunk in sorted(chunks, key=lambda c: c.get("score") or 0.0, reverse=True):
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        if len(text) <= budget:
            selected.append(text)
            budget -= len(text)
        else:
            selected.append(text[:budget])
            budget = 0
        if budget <= 0:
            break
    return selected


def _is_daily_limit(exc: RateLimitError) -> bool:
    """Daily (TPD) quota exhaustion cannot be fixed by short backoff, so retries
    are pointless. Per-minute (TPM) limits reset in seconds and are retryable."""
    return "tokens per day" in str(exc)


def _create_completion(prompt: str) -> str:
    last_error: Exception | None = None

    # Try each available key at most once for daily-limit errors
    for key_attempt in range(len(_clients)):
        client = _get_next_client()
        if client is None:
            break

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model="groq/compound-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=250,
                )
                return response.choices[0].message.content
            except RateLimitError as exc:
                last_error = exc
                if _is_daily_limit(exc):
                    logger.error(
                        "Groq daily token quota exhausted on key (attempt %d/%d): %s",
                        key_attempt + 1,
                        len(_clients),
                        exc,
                    )
                    _mark_key_exhausted(client)
                    break  # Move to next key instead of retrying same key
                delay = attempt * 5.0
                logger.warning(
                    "LLM rate limited (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt,
                    MAX_RETRIES,
                    exc,
                    delay,
                )
                time.sleep(delay)
            except (APIConnectionError, APITimeoutError) as exc:
                last_error = exc
                delay = attempt * 5.0
                logger.warning(
                    "LLM request failed (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt,
                    MAX_RETRIES,
                    exc,
                    delay,
                )
                time.sleep(delay)
            except APIStatusError as exc:
                if exc.status_code == 413:
                    last_error = exc
                    logger.error(
                        "Groq rejected an oversized request (HTTP 413). "
                        "Context capped at %d, system prompt at %d. Not retrying: %s",
                        MAX_CONTEXT_CHARS,
                        MAX_SYSTEM_PROMPT_CHARS,
                        exc,
                    )
                    break  # Don't retry — request is too large for any key
                raise exc

    if last_error:
        raise last_error
    raise RuntimeError(
        "All Groq API keys are exhausted. Add more keys to .env or wait for daily reset."
    )

def generate_answer(question: str, context: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
    # Truncate system prompt to prevent HTTP 413 (Request Entity Too Large).
    if len(system_prompt) > MAX_SYSTEM_PROMPT_CHARS:
        system_prompt = system_prompt[:MAX_SYSTEM_PROMPT_CHARS] + "\n..."
        logger.warning(
            "System prompt truncated to %d chars to avoid Groq size limit.",
            MAX_SYSTEM_PROMPT_CHARS,
        )

    prompt = f"""{system_prompt}

Context:
{context}

Question: {question}

Answer:"""

    # Safety: hard-cap the entire prompt well below Groq's entity-size limit.
    max_total = 20_000
    if len(prompt) > max_total:
        prompt = prompt[:max_total]
        logger.warning("Full prompt truncated to %d chars.", max_total)

    response = _create_completion(prompt)

    return response