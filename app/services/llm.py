import time
import logging
from groq import Groq, RateLimitError, APIConnectionError, APITimeoutError
from app.config import GROQ_API_KEY
from app.db import DEFAULT_SYSTEM_PROMPT, FALLBACK_MESSAGE, NO_RELEVANT_CONTEXT_FOUND

client = Groq(api_key=GROQ_API_KEY)
logger = logging.getLogger(__name__)

MAX_RETRIES = 3


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
    raise last_error

BEHAVIOR_RULES = f"""
UNIVERSAL RULES (apply on top of any persona above):

STEP 1 - CLASSIFY the user's message into one of two types:
  - TYPE A (CASUAL / SMALL TALK): greetings ("hi", "hello", "salam", "hey", "yo", "good morning"),
    how-are-you questions ("kya haal hai", "kaise ho", "what's up"), thanks, farewells, or any
    non-informational remark.
  - TYPE B (FACTUAL QUESTION): a genuine request for information about N2X System (services, projects,
    pricing, portfolio, contact details, technologies, capabilities, etc.).

STEP 2 - RESPOND according to the type:
  - TYPE A (CASUAL): reply naturally, warmly and conversationally in the user's language, keeping your
    persona/tone. You do NOT need the Context below for these. NEVER use the fallback message here.
  - TYPE B (FACTUAL): answer ONLY from the Context below. You MUST NOT use outside knowledge, general
    knowledge, or anything learned during training for any factual claim. If the Context is exactly
    "{NO_RELEVANT_CONTEXT_FOUND}", it means no relevant information was found in the knowledge base;
    in that case reply with EXACTLY this message and nothing else:
{FALLBACK_MESSAGE}
Do NOT guess, and do NOT answer a factual question from memory when the Context has no relevant information.

Keep answers short and to the point (2-4 sentences max).
"""


def generate_answer(question: str, context: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
    prompt = f"""{system_prompt}

{BEHAVIOR_RULES}

Context:
{context}

Question: {question}

Answer:"""

    response = _create_completion(prompt)

    return response