"""Application configuration. Everything overridable via environment variables."""
import os


class Settings:
    # Auth / security
    JWT_SECRET: str = os.environ.get("JYOTISH_JWT_SECRET", "dev-only-change-me-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = int(os.environ.get("JYOTISH_JWT_EXPIRE_HOURS", "168"))

    # Database. SQLite for zero-config local dev; point at Postgres for prod:
    #   JYOTISH_DATABASE_URL=postgresql+psycopg2://user:pass@host/db
    DATABASE_URL: str = os.environ.get(
        "JYOTISH_DATABASE_URL", f"sqlite:///{os.path.join(os.path.dirname(__file__), '..', 'jyotish.db')}"
    )

    # LLM provider: 'offline' (built-in deterministic responder, zero cost),
    # 'gemini' (free-tier Gemini API), 'ollama' (local), 'lmstudio' (local).
    LLM_PROVIDER: str = os.environ.get("JYOTISH_LLM_PROVIDER", "offline").lower()
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.environ.get("JYOTISH_GEMINI_MODEL", "gemini-3.5-flash")
    OLLAMA_URL: str = os.environ.get("JYOTISH_OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.environ.get("JYOTISH_OLLAMA_MODEL", "llama3.1")
    LMSTUDIO_URL: str = os.environ.get("JYOTISH_LMSTUDIO_URL", "http://localhost:1234/v1")
    LMSTUDIO_MODEL: str = os.environ.get("JYOTISH_LMSTUDIO_MODEL", "local-model")

    # Consent gate: whether chart data may be sent to a third-party LLM.
    LLM_EXTERNAL_CONSENT: bool = os.environ.get("JYOTISH_LLM_EXTERNAL_CONSENT", "false").lower() == "true"

    # Rate limiting (chat messages per minute per user)
    CHAT_RATE_LIMIT_PER_MIN: int = int(os.environ.get("JYOTISH_CHAT_RATE_LIMIT", "30"))

    FRONTEND_ORIGIN: str = os.environ.get("JYOTISH_FRONTEND_ORIGIN", "http://localhost:3000")


settings = Settings()
