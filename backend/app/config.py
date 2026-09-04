from dotenv import load_dotenv
import os
import logging

_load_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_load_dir, ".env"))

# Support multiple Groq API keys (comma-separated) for automatic rotation
# when one key hits the daily rate limit.
_raw_keys = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEYS: list[str] = [k.strip() for k in _raw_keys.split(",") if k.strip()]
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""

logging.getLogger(__name__).info(
    "Loaded %d Groq API key(s) for rotation.", len(GROQ_API_KEYS)
)

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change_this_password")
WHATSAPP_BUSINESS_NUMBER = os.getenv("WHATSAPP_BUSINESS_NUMBER", "")