import os
import secrets
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime, Text, ForeignKey, UniqueConstraint,
    create_engine, false, inspect, text,
)
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timezone
from .config import settings


def _utcnow() -> datetime:
    """Naive UTC timestamp (replacement for the deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

_url = settings.DATABASE_URL
# normalize postgres URLs to the psycopg2 driver
if _url.startswith("postgres://"):
    _url = "postgresql+psycopg2://" + _url.split("://", 1)[1]
elif _url.startswith("postgresql://") and "+psycopg2" not in _url:
    _url = "postgresql+psycopg2://" + _url.split("://", 1)[1]
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}
engine_db = create_engine(_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine_db, autoflush=False)
Base = declarative_base()


def new_token_nonce() -> str:
    return secrets.token_hex(16)


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"sqlite_autoincrement": True}
    id = Column(Integer, primary_key=True)
    # Random per-account value embedded in JWTs; tokens for a deleted account
    # never match a later account that reuses the same id.
    token_nonce = Column(String, nullable=False, default=new_token_nonce)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, default="")
    # Retained for audit/compatibility; enabled when service terms are accepted.
    llm_consent = Column(Boolean, default=False)
    llm_consent_at = Column(DateTime, nullable=True)
    terms_version = Column(String, nullable=True)
    terms_accepted_at = Column(DateTime, nullable=True)
    email_verified = Column(Boolean, nullable=False, default=False, server_default=false())
    created_at = Column(DateTime, default=_utcnow)
    # the birth profile (person) the chat/chart/calibration endpoints act on;
    # plain integer, validated against the user's own profiles on every use
    active_profile_id = Column(Integer, nullable=True)
    profiles = relationship("BirthProfile", back_populates="user",
                            cascade="all, delete-orphan", order_by="BirthProfile.id")
    conversations = relationship("Conversation", back_populates="user",
                                 cascade="all, delete-orphan")
    auth_tokens = relationship("AuthToken", cascade="all, delete-orphan")


class AuthToken(Base):
    """Single-use emailed token (password reset / email verification).
    Only the SHA-256 hash of the token is stored."""
    __tablename__ = "auth_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    purpose = Column(String, nullable=False)          # reset | verify
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class BirthProfile(Base):
    __tablename__ = "birth_profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    display_name = Column(String, default="")
    # who this chart is for, relative to the account owner
    relation = Column(String, nullable=False, default="self", server_default="self")
    year = Column(Integer); month = Column(Integer); day = Column(Integer)
    hour = Column(Integer); minute = Column(Integer); second = Column(Integer, default=0)
    place_name = Column(String); place_state = Column(String, default="")
    place_country = Column(String); latitude = Column(Float); longitude = Column(Float)
    timezone_name = Column(String, default="")
    utc_offset_hours = Column(Float)
    birth_time_precision = Column(String, default="exact")  # exact|approximate|unknown
    chart_json = Column(Text, default="")          # locked facts cache
    calc_fingerprint = Column(String, default="")
    calibration_state = Column(String, default="pending")  # pending|calibrated|partial|uncalibrated|insufficient_history|skipped
    predictions_allowed = Column(Boolean, default=False)
    rectified_from = Column(String, nullable=True)  # original "YYYY-MM-DD HH:MM:SS" if rectified
    # automatic (feedback-based) rectification already tried for this birth data
    rectification_attempted = Column(Boolean, nullable=False, default=False)
    # milestone-based time search already run for this birth data
    milestone_search_done = Column(Boolean, nullable=False, default=False)
    user = relationship("User", back_populates="profiles")
    conversations = relationship("Conversation", back_populates="profile",
                                 cascade="all, delete-orphan")
    calibrations = relationship("CalibrationEvent", back_populates="profile",
                                cascade="all, delete-orphan")
    predictions = relationship("PredictionRecord", cascade="all, delete-orphan",
                               order_by="PredictionRecord.id")
    milestones = relationship("UserMilestone", cascade="all, delete-orphan",
                              order_by="UserMilestone.id")


class CalibrationEvent(Base):
    __tablename__ = "calibration_events"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("birth_profiles.id"))
    event_id = Column(String)
    domain = Column(String)
    predicted_event = Column(Text)
    predicted_window_start = Column(String)
    predicted_window_end = Column(String)
    user_feedback = Column(String, default="")       # confirmed|partial|rejected|unknown
    actual_date = Column(String, default="")
    matched = Column(Boolean, default=False)
    rules_evaluated = Column(Text, default="")
    pillars_json = Column(Text, default="")
    chat_text = Column(Text, default="")
    calc_fingerprint = Column(String)
    asked = Column(Boolean, default=False)
    profile = relationship("BirthProfile", back_populates="calibrations")


class PredictionRecord(Base):
    """A future-domain analysis we gave, kept so we can ask afterwards whether
    it happened (track record)."""
    __tablename__ = "prediction_records"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("birth_profiles.id"), nullable=False, index=True)
    domain = Column(String)
    question = Column(Text)
    window_start = Column(Date)
    window_end = Column(Date)
    convergence = Column(String, default="")
    layer_verdicts = Column(Text, nullable=True)   # JSON: each precision filter's verdict
    protocol = Column(String, nullable=True)
    forecast = Column(String, nullable=True)     # event_indicated|abstain; NULL for legacy records
    event_type = Column(String, nullable=True)
    success_criteria = Column(Text, nullable=True)
    snapshot_json = Column(Text, nullable=True)  # frozen calculations, decision and final reply
    created_at = Column(DateTime, default=_utcnow)
    followup_asked_at = Column(DateTime, nullable=True)
    outcome = Column(String, nullable=True)   # happened|partly|did_not|unsure
    outcome_at = Column(DateTime, nullable=True)
    event_date = Column(Date, nullable=True)


class UserMilestone(Base):
    """A dated life event the user reported after calibration failed; used
    only to search for a better-fitting birth time (never to unlock
    predictions — user-supplied events aren't falsifiable checks)."""
    __tablename__ = "user_milestones"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("birth_profiles.id"), nullable=False, index=True)
    domain = Column(String, nullable=True)       # None until the user tells us
    description = Column(Text, default="")
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    profile_id = Column(Integer, ForeignKey("birth_profiles.id"), index=True)
    title = Column(String, default="Conversation")
    state = Column(String, default="cal_intro")  # cal_intro|cal_ask|cal_followup|open|rectify|rectify_collect|rectify_domain|rectify_confirm
    pending_event_id = Column(String, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    user = relationship("User", back_populates="conversations")
    profile = relationship("BirthProfile", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation",
                            cascade="all, delete-orphan", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    role = Column(String)          # user | assistant
    content = Column(Text)
    kind = Column(String, default="text")        # text|chart|options|notice
    meta_json = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    conversation = relationship("Conversation", back_populates="messages")
    feedback = relationship("MessageFeedback", cascade="all, delete-orphan")


class MessageFeedback(Base):
    """One thumbs up (+1) / down (-1) per user per assistant message."""
    __tablename__ = "message_feedback"
    __table_args__ = (UniqueConstraint("message_id", "user_id",
                                       name="uq_message_feedback_msg_user"),)
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)


class ProblemReport(Base):
    __tablename__ = "problem_reports"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    context_json = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASELINE_REVISION = "0001"


def _alembic_config(connection):
    from alembic.config import Config
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "alembic"))
    cfg.attributes["connection"] = connection
    return cfg


def init_db(eng=None):
    """Bring the schema to Alembic head. Databases created before Alembic
    (tables but no alembic_version) first get the old ad-hoc column fixes, are
    stamped at the baseline revision, and are then upgraded."""
    from alembic import command
    eng = eng or engine_db
    with eng.begin() as conn:
        if conn.dialect.name == "postgresql":
            # serialise concurrent workers booting at once; released on commit
            conn.execute(text("SELECT pg_advisory_xact_lock(7461902)"))
        cfg = _alembic_config(conn)
        tables = set(inspect(conn).get_table_names())
        if "users" in tables and "alembic_version" not in tables:
            _legacy_fixups(conn)
            command.stamp(cfg, BASELINE_REVISION)
        command.upgrade(cfg, "head")


def _legacy_fixups(conn):
    """Pre-Alembic schema repairs; the result matches revision 0001."""
    _migrate_token_nonce(conn)
    _add_column(conn, "birth_profiles", "rectified_from", "VARCHAR")
    _add_column(conn, "users", "llm_consent", "BOOLEAN")
    _add_column(conn, "users", "llm_consent_at", "TIMESTAMP")


def _add_column(conn, table: str, column: str, ddl_type: str):
    """Add a nullable column if an older table lacks it (pre-Alembic DBs only)."""
    cols = {c["name"] for c in inspect(conn).get_columns(table)}
    if column not in cols:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


def _migrate_token_nonce(conn):
    cols = {c["name"] for c in inspect(conn).get_columns("users")}
    if "token_nonce" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN token_nonce VARCHAR"))
    ids = conn.execute(text("SELECT id FROM users WHERE token_nonce IS NULL")).scalars().all()
    for uid in ids:
        conn.execute(text("UPDATE users SET token_nonce = :n WHERE id = :i AND token_nonce IS NULL"),
                     {"n": new_token_nonce(), "i": uid})


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
