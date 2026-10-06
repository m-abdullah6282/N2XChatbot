from dotenv import load_dotenv
import os
import logging

logger = logging.getLogger(__name__)

_load_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_load_dir, ".env"))

# ---------------------------------------------------------------------------
# Groq — multi-key rotation
# ---------------------------------------------------------------------------
# Support multiple Groq API keys (comma-separated) for automatic rotation
# when one key hits the daily rate limit.
_raw_keys = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEYS: list[str] = [k.strip() for k in _raw_keys.split(",") if k.strip()]
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""

logger.info("Loaded %d Groq API key(s) for rotation.", len(GROQ_API_KEYS))

# Plain chat model: "groq/compound-*" are agentic systems with built-in web
# search, which breaks "answer only from the knowledge base" and adds latency.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

# ---------------------------------------------------------------------------
# Bootstrap admin (only used when the admin_users table is empty)
# ---------------------------------------------------------------------------
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change_this_password")
WHATSAPP_BUSINESS_NUMBER = os.getenv("WHATSAPP_BUSINESS_NUMBER", "")

# ---------------------------------------------------------------------------
# Database (Postgres)
# ---------------------------------------------------------------------------
# Production (Render): DATABASE_URL is MANDATORY. If it is missing in prod we
# fail fast on boot instead of silently connecting to localhost (which would
# surface as a confusing "database down" error).
#
# Local dev: falls back to localhost only when APP_ENV=local (the default).
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    if os.getenv("APP_ENV", "local") == "local":
        DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/n2x_chatbot"
        logger.warning(
            "DATABASE_URL not set - using local dev fallback: %s",
            DATABASE_URL,
        )
    else:
        raise RuntimeError(
            "DATABASE_URL is not set. On Render/production you MUST provide it "
            "in the service's environment variables (Postgres -> Connection string)."
        )