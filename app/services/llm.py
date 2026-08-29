import time
import logging
from groq import Groq, RateLimitError, APIConnectionError, APITimeoutError, APIStatusError
from app.config import GROQ_API_KEY
from app.db import DEFAULT_SYSTEM_PROMPT

client = Groq(api_key=GROQ_API_KEY)
logger = logging.getLogger(__name__)

MAX_RETRIES = 3

# groq/compound-mini exposes a 131,072-token context window (~500KB of text).
# We deliberately cap the retrieved context far below that: answers are 2-4
# sentences so a handful of chunks is plenty, and staying well under the window
# also keeps the HTTP request body below Groq's entity-size cap (oversized
# bodies surface as HTTP 413 "Request Entity Too Large").
MAX_CONTEXT_CHARS = 16_000


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
                    "Groq daily token quota exhausted (no retry): %s", exc
                )
                raise exc
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
            # 413 means the prompt body exceeds Groq's entity-size limit.
            # Its only fix is a smaller prompt, which truncation already
            # enforces, so retrying the identical payload is pointless.
            if exc.status_code == 413:
                last_error = exc
                logger.error(
                    "Groq rejected an oversized request (HTTP 413). Context is "
                    "already capped at MAX_CONTEXT_CHARS=%d; check for an "
                    "oversized agent system prompt. Not retrying: %s",
                    MAX_CONTEXT_CHARS,
                    exc,
                )
            raise exc
    raise last_error

def generate_answer(question: str, context: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
    prompt = f"""{system_prompt}

Context:
{context}

Question: {question}

Answer:"""

    response = _create_completion(prompt)

    return response