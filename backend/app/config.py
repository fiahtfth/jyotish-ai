"""Application configuration. Everything overridable via environment variables."""
import os

from dotenv import load_dotenv

# local secrets live in backend/.env (git-ignored); real env vars take precedence
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


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
    # 'gemini'/'groq'/'openrouter' (external APIs), 'ollama'/'lmstudio' (local).
    LLM_PROVIDER: str = os.environ.get("JYOTISH_LLM_PROVIDER", "offline").lower()
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.environ.get("JYOTISH_GEMINI_MODEL", "gemini-3.5-flash")
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.environ.get("JYOTISH_GROQ_MODEL", "openai/gpt-oss-120b")
    OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = os.environ.get("JYOTISH_OPENROUTER_MODEL", "openrouter/free")
    OLLAMA_URL: str = os.environ.get("JYOTISH_OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.environ.get("JYOTISH_OLLAMA_MODEL", "llama3.1")
    LMSTUDIO_URL: str = os.environ.get("JYOTISH_LMSTUDIO_URL", "http://localhost:1234/v1")
    LMSTUDIO_MODEL: str = os.environ.get("JYOTISH_LMSTUDIO_MODEL", "local-model")

    # Consent gate: whether chart data may be sent to a third-party LLM.
    LLM_EXTERNAL_CONSENT: bool = os.environ.get("JYOTISH_LLM_EXTERNAL_CONSENT", "false").lower() == "true"

    # Bounds on LLM work per chat turn: overall wall-clock budget across all
    # providers/retries, and max concurrent turns calling an LLM (excess turns
    # get the offline responder instead of waiting).
    LLM_TURN_DEADLINE_SECONDS: float = float(os.environ.get("JYOTISH_LLM_TURN_DEADLINE", "30"))
    LLM_MAX_CONCURRENCY: int = int(os.environ.get("JYOTISH_LLM_MAX_CONCURRENCY", "4"))

    # Rate limiting (chat messages per minute per user)
    CHAT_RATE_LIMIT_PER_MIN: int = int(os.environ.get("JYOTISH_CHAT_RATE_LIMIT", "30"))

    # Email (password reset / verification). With no SMTP host the mailer only
    # logs (dev mode). PUBLIC_BASE_URL is used to build links in emails.
    SMTP_HOST: str = os.environ.get("JYOTISH_SMTP_HOST", "")
    SMTP_PORT: int = int(os.environ.get("JYOTISH_SMTP_PORT", "587"))
    SMTP_USER: str = os.environ.get("JYOTISH_SMTP_USER", "")
    SMTP_PASSWORD: str = os.environ.get("JYOTISH_SMTP_PASSWORD", "")
    SMTP_FROM: str = os.environ.get("JYOTISH_SMTP_FROM", "Jyotish AI <noreply@localhost>")
    PUBLIC_BASE_URL: str = os.environ.get("JYOTISH_PUBLIC_BASE_URL", "http://localhost:3000").rstrip("/")

    # Owner accounts (comma-separated emails) allowed to read /api/admin/*
    ADMIN_EMAILS: frozenset = frozenset(
        e.strip().lower() for e in os.environ.get("JYOTISH_ADMIN_EMAILS", "").split(",")
        if e.strip())

    FRONTEND_ORIGIN: str = os.environ.get("JYOTISH_FRONTEND_ORIGIN", "http://localhost:3000")


settings = Settings()

if (settings.JWT_SECRET == "dev-only-change-me-in-production"
        and os.environ.get("JYOTISH_ENV") == "prod"):
    raise RuntimeError("JYOTISH_JWT_SECRET must be set to a non-default value when JYOTISH_ENV=prod")
