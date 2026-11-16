"""Jyotish AI — FastAPI application."""
import json
import time
from collections import defaultdict, deque
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import geo
from .auth import create_token, current_user, hash_password, verify_password
from .chat import orchestrator
from .config import settings
from .db import (
    BirthProfile, CalibrationEvent, Conversation, Message, User, get_db, init_db,
)
from .astro.engine import BirthInput, engine, fingerprint as calc_fp
from .schemas import (
    BirthProfileIn, BirthProfileOut, ChatIn, LoginIn, MessageOut,
    PlaceSearchOut, RegisterIn, TokenOut,
)

app = FastAPI(title="Jyotish AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

_rate: dict[int, deque] = defaultdict(deque)


@app.on_event("startup")
def startup():  # noqa: deprecated-but-functional
    init_db()
    engine.compute  # warm import


def _rate_limit(user_id: int):
    now = time.time()
    q = _rate[user_id]
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= settings.CHAT_RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "slow down — too many messages")
    q.append(now)


# ------------------------------------------------------------- auth

@app.post("/api/auth/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(409, "account already exists")
    u = User(email=body.email.lower(), password_hash=hash_password(body.password),
             display_name=body.display_name)
    db.add(u)
    db.commit()
    return TokenOut(access_token=create_token(u.id), needs_birth_profile=True)


@app.post("/api/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.email == body.email.lower()).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "invalid credentials")
    return TokenOut(access_token=create_token(u.id),
                    needs_birth_profile=u.profile is None)


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "display_name": user.display_name,
            "has_profile": user.profile is not None}


@app.delete("/api/auth/me")
def delete_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    for c in user.conversations:
        db.delete(c)
    if user.profile:
        db.delete(user.profile)
    db.delete(user)
    db.commit()
    return {"deleted": True}


# ------------------------------------------------------------- geo

@app.get("/api/geo/search", response_model=list[PlaceSearchOut])
def geo_search(q: str = Query(min_length=2), user: User = Depends(current_user)):
    return geo.search_places(q)


# ------------------------------------------------------------- birth profile

def _profile_out(p: BirthProfile) -> dict:
    return {
        "display_name": p.display_name or "", "year": p.year, "month": p.month,
        "day": p.day, "hour": p.hour, "minute": p.minute, "second": p.second or 0,
        "place_name": p.place_name, "place_state": p.place_state,
        "place_country": p.place_country, "latitude": p.latitude,
        "longitude": p.longitude, "birth_time_precision": p.birth_time_precision,
        "timezone_name": p.timezone_name, "utc_offset_hours": p.utc_offset_hours,
        "calc_fingerprint": p.calc_fingerprint,
        "calibration_state": p.calibration_state,
        "predictions_allowed": p.predictions_allowed,
    }


@app.get("/api/profile", response_model=BirthProfileOut)
def get_profile(user: User = Depends(current_user)):
    if not user.profile:
        raise HTTPException(404, "no birth profile yet")
    return _profile_out(user.profile)


@app.put("/api/profile", response_model=BirthProfileOut)
def put_profile(body: BirthProfileIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    birth_dt = datetime(body.year, body.month, body.day, body.hour, body.minute)
    resolved = geo.resolve_place(body.place_name, state=body.place_state,
                                 country=body.place_country, lat=body.latitude,
                                 lon=body.longitude, birth_dt=birth_dt)
    p = user.profile
    if p is None:
        p = BirthProfile(user_id=user.id)
        db.add(p)
    material_change = (
        p.id is None or
        (p.year, p.month, p.day, p.hour, p.minute, p.second or 0,
         round(p.latitude or 0, 4), round(p.longitude or 0, 4),
         p.birth_time_precision)
        != (body.year, body.month, body.day, body.hour, body.minute, body.second,
            round(resolved["latitude"], 4), round(resolved["longitude"], 4),
            body.birth_time_precision)
    )
    for k in ("display_name", "year", "month", "day", "hour", "minute", "second",
              "place_name", "place_state", "place_country", "birth_time_precision"):
        setattr(p, k, getattr(body, k) if hasattr(body, k) else getattr(p, k))
    p.place_name = resolved["name"]
    p.place_state = resolved["state"]
    p.place_country = resolved["country"]
    p.latitude = resolved["latitude"]
    p.longitude = resolved["longitude"]
    p.timezone_name = resolved["timezone_name"]
    p.utc_offset_hours = resolved["utc_offset_hours"]

    if material_change:
        # recompute the locked chart + fingerprint; never silently mutate them
        b = orchestrator.birth_input(p)
        facts = engine.compute(b)
        p.chart_json = json.dumps(facts)
        p.calc_fingerprint = calc_fp({"birth_time_precision": p.birth_time_precision})
        p.calibration_state = "pending"
        p.predictions_allowed = False
        # mark old calibration events for re-issue on next conversation start
    db.commit()
    return _profile_out(p)


# ------------------------------------------------------------- chat

def _msg_out(m: Message) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "kind": m.kind,
            "meta": json.loads(m.meta_json or "{}"), "created_at": m.created_at.isoformat()}


def _user_conversation(db: Session, user: User) -> Conversation:
    conv = (db.query(Conversation)
            .filter(Conversation.user_id == user.id)
            .order_by(Conversation.id.desc()).first())
    if conv is None:
        conv = Conversation(user_id=user.id)
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv


@app.get("/api/chat/history", response_model=list[MessageOut])
def chat_history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.profile:
        raise HTTPException(428, "birth profile required")
    conv = _user_conversation(db, user)
    if not conv.messages:
        orchestrator.start_conversation(db, conv, user.profile)
        db.refresh(conv)
    return [_msg_out(m) for m in conv.messages]


@app.post("/api/chat/send", response_model=list[MessageOut])
def chat_send(body: ChatIn, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    if not user.profile:
        raise HTTPException(428, "birth profile required")
    _rate_limit(user.id)
    conv = _user_conversation(db, user)
    if not conv.messages:
        orchestrator.start_conversation(db, conv, user.profile)
        db.refresh(conv)
    new_msgs = orchestrator.handle_message(db, conv, user.profile, body.text)
    return [_msg_out(m) for m in new_msgs]


@app.post("/api/chat/reset")
def chat_reset(user: User = Depends(current_user), db: Session = Depends(get_db)):
    conv = _user_conversation(db, user)
    for m in list(conv.messages):
        db.delete(m)
    conv.state = "cal_intro"
    conv.pending_event_id = ""
    if user.profile:
        db.query(CalibrationEvent).filter(
            CalibrationEvent.profile_id == user.profile.id).delete()
        user.profile.calibration_state = "pending"
        user.profile.predictions_allowed = False
    db.commit()
    return {"reset": True}


# ------------------------------------------------------------- charts

@app.get("/api/chart/{varga}")
def get_chart(varga: str, user: User = Depends(current_user)):
    if not user.profile:
        raise HTTPException(428, "birth profile required")
    v = varga.upper()
    facts = orchestrator.chart_facts(user.profile)
    if v not in facts["vargas"]:
        raise HTTPException(404, f"{v} not computed")
    return {"varga": v, "lagna": facts["lagna"], "chart": facts["vargas"][v],
            "fingerprint": user.profile.calc_fingerprint}


@app.get("/api/calibration")
def calibration_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.profile:
        raise HTTPException(428, "birth profile required")
    evs = (db.query(CalibrationEvent)
           .filter(CalibrationEvent.profile_id == user.profile.id).all())
    return {
        "state": user.profile.calibration_state,
        "predictions_allowed": user.profile.predictions_allowed,
        "events": [{
            "event_id": e.event_id, "domain": e.domain,
            "predicted_event": e.predicted_event,
            "window": {"start": e.predicted_window_start, "end": e.predicted_window_end},
            "user_feedback": e.user_feedback, "actual_date": e.actual_date,
            "matched": e.matched,
        } for e in evs],
    }


@app.get("/api/health")
def health():
    return {"ok": True, "llm_provider": settings.LLM_PROVIDER}
