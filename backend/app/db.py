import secrets
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, create_engine,
    inspect, text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from .config import settings

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
    created_at = Column(DateTime, default=datetime.utcnow)
    profile = relationship("BirthProfile", back_populates="user", uselist=False,
                           cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user",
                                 cascade="all, delete-orphan")


class BirthProfile(Base):
    __tablename__ = "birth_profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    display_name = Column(String, default="")
    year = Column(Integer); month = Column(Integer); day = Column(Integer)
    hour = Column(Integer); minute = Column(Integer); second = Column(Integer, default=0)
    place_name = Column(String); place_state = Column(String, default="")
    place_country = Column(String); latitude = Column(Float); longitude = Column(Float)
    timezone_name = Column(String, default="")
    utc_offset_hours = Column(Float)
    birth_time_precision = Column(String, default="exact")  # exact|approximate|unknown
    chart_json = Column(Text, default="")          # locked facts cache
    calc_fingerprint = Column(String, default="")
    calibration_state = Column(String, default="pending")  # pending|calibrated|partial|uncalibrated
    predictions_allowed = Column(Boolean, default=False)
    user = relationship("User", back_populates="profile")
    calibrations = relationship("CalibrationEvent", back_populates="profile",
                                cascade="all, delete-orphan")


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


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String, default="Conversation")
    state = Column(String, default="cal_intro")  # cal_intro|cal_ask|cal_followup|open|rectify
    pending_event_id = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="conversations")
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
    created_at = Column(DateTime, default=datetime.utcnow)
    conversation = relationship("Conversation", back_populates="messages")


def init_db():
    Base.metadata.create_all(engine_db)
    _migrate_token_nonce()


def _migrate_token_nonce():
    cols = {c["name"] for c in inspect(engine_db).get_columns("users")}
    with engine_db.begin() as conn:
        if "token_nonce" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN token_nonce VARCHAR"))
        ids = conn.execute(text("SELECT id FROM users WHERE token_nonce IS NULL")).scalars().all()
        for uid in ids:
            conn.execute(text("UPDATE users SET token_nonce = :n WHERE id = :i"),
                         {"n": new_token_nonce(), "i": uid})


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
