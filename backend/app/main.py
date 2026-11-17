"""Jyotish AI — FastAPI application."""
import json
import logging
import os
import queue
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, object_session

from . import geo, mailer
from .auth import (
    consume_auth_token, create_token, current_user, hash_password, issue_auth_token,
    verify_password,
)
from .chat import orchestrator
from .config import settings
from .db import (
    BirthProfile, CalibrationEvent, Conversation, Message, MessageFeedback, PredictionRecord,
    ProblemReport, SessionLocal, UserMilestone,
    User, get_db, init_db, new_token_nonce,
)
from .astro.engine import BirthInput, engine, birth_fingerprint
from .schemas import (
    MAX_PROFILES, BirthProfileIn, BirthProfileOut, ChatIn, ConsentIn, FeedbackIn, ForgotIn,
    LoginIn, MessageOut, PlaceSearchOut, ProfileListItem, RegisterIn, ReportIn, ResetIn,
    TokenIn, TokenOut,
)

log = logging.getLogger(__name__)

# Optional error tracking: enabled only when SENTRY_DSN is set. Request bodies
# and PII are never sent — they contain birth data and chat text.
if os.environ.get("SENTRY_DSN"):
    import sentry_sdk
    sentry_sdk.init(dsn=os.environ["SENTRY_DSN"],
                    environment=os.environ.get("JYOTISH_ENV", "dev"),
                    send_default_pii=False, max_request_body_size="never",
                    traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0")))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    engine.compute  # warm import
    yield


app = FastAPI(title="Jyotish AI", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
async def no_store_api(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Authorization"
    return response

_rate: dict[int, deque] = defaultdict(deque)


def _rate_limit(user_id: int):
    now = time.time()
    q = _rate[user_id]
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= settings.CHAT_RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "slow down — too many messages")
    q.append(now)


# ------------------------------------------------------------- auth

# in-memory sliding-window throttle for login/register (per process)
AUTH_MAX_ATTEMPTS = 10
AUTH_WINDOW_S = 300
_auth_attempts: dict[str, deque] = {}


def reset_auth_throttle():
    _auth_attempts.clear()


def _throttle_check(key: str, limit: int = AUTH_MAX_ATTEMPTS):
    """Raise 429 if `key` is at its limit; also prunes expired entries."""
    now = time.monotonic()
    for k in list(_auth_attempts):
        q = _auth_attempts[k]
        while q and q[0] < now - AUTH_WINDOW_S:
            q.popleft()
        if not q:
            del _auth_attempts[k]
    if len(_auth_attempts.get(key, ())) >= limit:
        raise HTTPException(429, "too many attempts — try again in a few minutes")


def _throttle_record(key: str):
    _auth_attempts.setdefault(key, deque()).append(time.monotonic())


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"

@app.post("/api/auth/register", response_model=TokenOut)
def register(body: RegisterIn, request: Request, background: BackgroundTasks,
             db: Session = Depends(get_db)):
    ip_key = "ip:" + _client_ip(request)
    _throttle_check(ip_key)
    _throttle_record(ip_key)
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(409, "account already exists")
    u = User(email=body.email.lower(), password_hash=hash_password(body.password),
             display_name=body.display_name, llm_consent=body.llm_consent,
             llm_consent_at=_now() if body.llm_consent else None)
    db.add(u)
    db.flush()
    raw = issue_auth_token(db, u, "verify")
    db.commit()
    _queue_link_email(background, u.email, "verify", raw)
    return TokenOut(access_token=create_token(u), needs_birth_profile=True)


def _queue_link_email(background: BackgroundTasks, to: str, purpose: str, raw: str):
    # sent after the response so timing doesn't reveal whether an account exists
    base = settings.PUBLIC_BASE_URL
    if purpose == "reset":
        subject = "Reset your Jyotish AI password"
        body = (f"Use this link to choose a new password (valid for 1 hour):\n\n"
                f"{base}/reset?token={raw}\n\n"
                "If you didn't ask for this, you can ignore this email.")
    else:
        subject = "Verify your Jyotish AI email"
        body = (f"Confirm your email address (link valid for 48 hours):\n\n"
                f"{base}/verify?token={raw}\n")
    background.add_task(mailer.send_email, to, subject, body)


@app.post("/api/auth/forgot")
def forgot_password(body: ForgotIn, request: Request, background: BackgroundTasks,
                    db: Session = Depends(get_db)):
    ip_key = "ip:" + _client_ip(request)
    _throttle_check(ip_key)
    _throttle_record(ip_key)
    u = db.query(User).filter(User.email == body.email.lower()).first()
    if u:
        raw = issue_auth_token(db, u, "reset")
        db.commit()
        _queue_link_email(background, u.email, "reset", raw)
    return {"ok": True}


@app.post("/api/auth/reset")
def reset_password(body: ResetIn, db: Session = Depends(get_db)):
    u = consume_auth_token(db, body.token, "reset")
    if u is None:
        raise HTTPException(400, "invalid or expired link")
    u.password_hash = hash_password(body.password)
    u.token_nonce = new_token_nonce()      # logs out every existing session
    db.commit()
    return {"ok": True}


@app.post("/api/auth/verify")
def verify_email(body: TokenIn, db: Session = Depends(get_db)):
    u = consume_auth_token(db, body.token, "verify")
    if u is None:
        raise HTTPException(400, "invalid or expired link")
    u.email_verified = True
    db.commit()
    return {"ok": True}


@app.post("/api/auth/verify/resend")
def resend_verification(background: BackgroundTasks, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    if user.email_verified:
        return {"ok": True}
    key = f"resend:{user.id}"
    _throttle_check(key, limit=3)
    _throttle_record(key)
    raw = issue_auth_token(db, user, "verify")
    db.commit()
    _queue_link_email(background, user.email, "verify", raw)
    return {"ok": True}


@app.post("/api/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    # IP budget counts every attempt; the per-email budget counts only FAILED
    # logins, so an attacker can't lock a victim out with successful-looking traffic
    ip_key = "ip:" + _client_ip(request)
    email_key = "email:" + body.email.lower()
    _throttle_check(ip_key)
    _throttle_check(email_key)
    _throttle_record(ip_key)
    u = db.query(User).filter(User.email == body.email.lower()).first()
    if not u or not verify_password(body.password, u.password_hash):
        _throttle_record(email_key)
        raise HTTPException(401, "invalid credentials")
    return TokenOut(access_token=create_token(u),
                    needs_birth_profile=not u.profiles)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    p = _active_profile(user)
    return {"id": user.id, "email": user.email, "display_name": user.display_name,
            "has_profile": p is not None,
            "active_profile_id": p.id if p else None,
            "is_admin": _is_admin(user),
            "llm_consent": bool(user.llm_consent),
            "email_verified": bool(user.email_verified)}


@app.put("/api/auth/consent")
def set_consent(body: ConsentIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Grant or withdraw consent to third-party AI providers. Withdrawal takes
    effect on the next message (replies fall back to the offline responder)."""
    user.llm_consent = body.llm_consent
    user.llm_consent_at = _now()
    db.commit()
    return {"llm_consent": bool(user.llm_consent)}


def _iso(d):
    return d.isoformat() if d else None


@app.get("/api/auth/me/export")
def export_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Everything stored about the account, as JSON (data-portability request).
    Per-profile data (events, predictions, milestones, conversations) carries
    the owning profile_id."""
    active = _active_profile(user)
    pids = [p.id for p in user.profiles]
    events = [{
        "profile_id": e.profile_id,
        "event_id": e.event_id, "domain": e.domain,
        "predicted_event": e.predicted_event,
        "window": {"start": e.predicted_window_start, "end": e.predicted_window_end},
        "user_feedback": e.user_feedback, "actual_date": e.actual_date,
        "matched": e.matched,
    } for e in db.query(CalibrationEvent).filter(CalibrationEvent.profile_id.in_(pids))
        .order_by(CalibrationEvent.id).all()] if pids else []
    my_votes = (db.query(MessageFeedback).filter(MessageFeedback.user_id == user.id)
                .order_by(MessageFeedback.id).all())
    reports = (db.query(ProblemReport).filter(ProblemReport.user_id == user.id)
               .order_by(ProblemReport.id).all())
    return {
        "exported_at": _iso(_now()),
        "account": {"email": user.email, "display_name": user.display_name,
                    "created_at": _iso(user.created_at),
                    "llm_consent": bool(user.llm_consent),
                    "email_verified": bool(user.email_verified),
                    "llm_consent_at": _iso(user.llm_consent_at)},
        # legacy key: the active profile
        "birth_profile": ({**_profile_out(active), "rectified_from": active.rectified_from}
                          if active else None),
        "birth_profiles": [{**_profile_out(p), "rectified_from": p.rectified_from,
                            "is_active": bool(active and p.id == active.id)}
                           for p in user.profiles],
        "calibration_events": events,
        "predictions": _prediction_rows(db, pids),
        "milestones": [{"profile_id": m.profile_id, "domain": m.domain,
                        "description": m.description, "year": m.year,
                        "month": m.month, "created_at": _iso(m.created_at)}
                       for p in user.profiles for m in p.milestones],
        "conversations": [{
            "profile_id": c.profile_id,
            "created_at": _iso(c.created_at),
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "kind": m.kind,
                          "created_at": _iso(m.created_at)} for m in c.messages],
        } for c in user.conversations],
        "message_feedback": [{"message_id": f.message_id, "rating": f.rating,
                              "comment": f.comment, "created_at": _iso(f.created_at)}
                             for f in my_votes],
        "problem_reports": [{"text": r.text, "context": json.loads(r.context_json or "{}"),
                             "created_at": _iso(r.created_at)} for r in reports],
    }


@app.delete("/api/auth/me")
def delete_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(MessageFeedback).filter(MessageFeedback.user_id == user.id).delete()
    db.query(ProblemReport).filter(ProblemReport.user_id == user.id).delete()
    for c in user.conversations:
        db.delete(c)
    for p in list(user.profiles):
        db.delete(p)
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
        "id": p.id, "relation": p.relation or "self",
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


def _active_profile(user: User) -> BirthProfile | None:
    """The person the chat/chart/calibration endpoints act on. Falls back to the
    user's first profile if the stored id is unset or not theirs."""
    db = object_session(user)
    p = None
    if user.active_profile_id:
        p = db.get(BirthProfile, user.active_profile_id)
        if p is not None and p.user_id != user.id:
            p = None
    if p is None:
        p = (db.query(BirthProfile).filter(BirthProfile.user_id == user.id)
             .order_by(BirthProfile.id).first())
        if p is not None:
            user.active_profile_id = p.id       # persisted by the next commit
    return p


def _require_profile(user: User) -> BirthProfile:
    p = _active_profile(user)
    if p is None:
        raise HTTPException(428, "birth profile required")
    return p


def _owned_profile(db: Session, user: User, profile_id: int) -> BirthProfile:
    p = db.get(BirthProfile, profile_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "profile not found")      # never reveal others' ids
    return p


def _profile_item(p: BirthProfile, active_id: int | None) -> dict:
    return {"id": p.id, "display_name": p.display_name or "", "relation": p.relation or "self",
            "calibration_state": p.calibration_state or "pending",
            "predictions_allowed": bool(p.predictions_allowed),
            "is_active": p.id == active_id}


def _profile_response(user: User, p: BirthProfile) -> dict:
    return {**_profile_out(p), "is_active": user.active_profile_id == p.id}


@app.get("/api/profile", response_model=BirthProfileOut)
def get_profile(user: User = Depends(current_user)):
    p = _active_profile(user)
    if not p:
        raise HTTPException(404, "no birth profile yet")
    return _profile_response(user, p)


def _save_profile(db: Session, user: User, p: BirthProfile, body: BirthProfileIn) -> BirthProfile:
    """Validate/resolve the birth data and write it to `p` (new or existing),
    resetting calibration when the birth data materially changed. Commits."""
    birth_dt = datetime(body.year, body.month, body.day, body.hour, body.minute)
    resolved = geo.resolve_place(body.place_name, state=body.place_state,
                                 country=body.place_country, lat=body.latitude,
                                 lon=body.longitude, birth_dt=birth_dt)
    is_new = p.id is None
    if is_new:
        p.user_id = user.id
        db.add(p)
    subject_before = (p.display_name or "", p.relation or "self")
    material_change = (
        is_new or
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
    if body.relation is not None:
        p.relation = body.relation
    elif is_new:
        p.relation = "self"
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
        p.calc_fingerprint = birth_fingerprint(b)
        p.rectified_from = None  # user-edited birth details supersede any rectification
        # new birth data gets a fresh chance at automatic and milestone rectification
        p.rectification_attempted = False
        p.milestone_search_done = False
        if not is_new:
            db.query(UserMilestone).filter(UserMilestone.profile_id == p.id).delete()
        p.calibration_state = "pending"
        p.predictions_allowed = False
        # the old calibration answers no longer apply to the new chart —
        # retire them and send the conversation back to calibration, else
        # a user who edits birth details gets permanently locked out
        if not is_new:
            db.query(CalibrationEvent).filter(
                CalibrationEvent.profile_id == p.id).delete()
            conv = _profile_conversation(db, p)
            conv.state = "cal_intro"
            conv.pending_event_id = ""
    elif subject_before != (p.display_name or "", p.relation or "self"):
        orchestrator.refresh_event_wording(db, p)
    db.flush()
    if user.active_profile_id is None:
        user.active_profile_id = p.id
    db.commit()
    return p


@app.put("/api/profile", response_model=BirthProfileOut)
def put_profile(body: BirthProfileIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Create (first time) or edit the ACTIVE profile."""
    p = _active_profile(user) or BirthProfile()
    _save_profile(db, user, p, body)
    return _profile_response(user, p)


@app.get("/api/profiles", response_model=list[ProfileListItem])
def list_profiles(user: User = Depends(current_user)):
    active = _active_profile(user)
    return [_profile_item(p, active.id if active else None) for p in user.profiles]


@app.post("/api/profiles", response_model=BirthProfileOut)
def create_profile(body: BirthProfileIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    if len(user.profiles) >= MAX_PROFILES:
        raise HTTPException(400, f"profile limit reached ({MAX_PROFILES})")
    p = BirthProfile()
    _save_profile(db, user, p, body)
    user.active_profile_id = p.id          # a new person becomes the active one
    db.commit()
    return _profile_response(user, p)


@app.put("/api/profiles/{profile_id}", response_model=BirthProfileOut)
def put_profile_by_id(profile_id: int, body: BirthProfileIn,
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _owned_profile(db, user, profile_id)
    _save_profile(db, user, p, body)
    return _profile_response(user, p)


@app.get("/api/profiles/{profile_id}", response_model=BirthProfileOut)
def get_profile_by_id(profile_id: int, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    return _profile_response(user, _owned_profile(db, user, profile_id))


@app.post("/api/profiles/{profile_id}/activate", response_model=ProfileListItem)
def activate_profile(profile_id: int, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    p = _owned_profile(db, user, profile_id)
    user.active_profile_id = p.id
    db.commit()
    return _profile_item(p, p.id)


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    p = _owned_profile(db, user, profile_id)
    others = [x for x in user.profiles if x.id != p.id]
    if not others:
        raise HTTPException(400, "can't delete your only profile")
    was_active = _active_profile(user).id == p.id
    # cascades: conversation -> messages -> feedback, events, milestones, predictions
    db.delete(p)
    if was_active:
        user.active_profile_id = others[0].id
    db.commit()
    return {"deleted": True, "active_profile_id": user.active_profile_id}


# ------------------------------------------------------------- chat

def _msg_out(m: Message, rating: int = 0) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "kind": m.kind,
            "meta": json.loads(m.meta_json or "{}"), "created_at": m.created_at.isoformat(),
            "rating": rating}


def _profile_conversation(db: Session, p: BirthProfile) -> Conversation:
    """Each profile has its own conversation."""
    conv = (db.query(Conversation)
            .filter(Conversation.profile_id == p.id)
            .order_by(Conversation.id.desc()).first())
    if conv is None:
        conv = Conversation(user_id=p.user_id, profile_id=p.id)
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv


@app.get("/api/chat/history", response_model=list[MessageOut])
def chat_history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _require_profile(user)
    conv = _profile_conversation(db, p)
    if not conv.messages:
        orchestrator.start_conversation(db, conv, p)
        db.refresh(conv)
    ids = [m.id for m in conv.messages]
    ratings = dict(db.query(MessageFeedback.message_id, MessageFeedback.rating)
                   .filter(MessageFeedback.user_id == user.id,
                           MessageFeedback.message_id.in_(ids)).all()) if ids else {}
    return [_msg_out(m, ratings.get(m.id, 0)) for m in conv.messages]


@app.post("/api/chat/send", response_model=list[MessageOut])
def chat_send(body: ChatIn, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    p = _require_profile(user)
    _rate_limit(user.id)
    conv = _profile_conversation(db, p)
    if not conv.messages:
        orchestrator.start_conversation(db, conv, p)
        db.refresh(conv)
    new_msgs = orchestrator.handle_message(db, conv, p, body.text)
    return [_msg_out(m) for m in new_msgs]


def _save_user_message_after_failure(db: Session, conv_id: int | None, text: str):
    """A failed turn commits nothing, so keep the user's own message — the
    client shows it again on the next history load instead of losing it."""
    if conv_id is None:
        return
    try:
        db.rollback()
        conv = db.get(Conversation, conv_id)
        if conv is not None:
            orchestrator._add_msg(db, conv, "user", text)
            db.commit()
    except Exception:
        log.exception("could not save user message after failed turn")
        db.rollback()


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@app.post("/api/chat/stream")
def chat_stream(body: ChatIn, user: User = Depends(current_user)):
    """Server-sent events variant of /api/chat/send: zero or more
    {"type":"delta"}, then one {"type":"done","messages":[...]} (authoritative;
    may differ from the streamed text) or {"type":"error"}."""
    p = _require_profile(user)
    _rate_limit(user.id)
    user_id, profile_id, text = user.id, p.id, body.text
    events: queue.Queue = queue.Queue()

    def work():
        # own session: the request-scoped one may be closed before the stream ends
        db = SessionLocal()
        conv_id = None
        try:
            # bound to the profile active when the request was made, even if
            # the user switches person while this turn is running
            prof = db.get(BirthProfile, profile_id)
            conv = _profile_conversation(db, prof)
            conv_id = conv.id
            if not conv.messages:
                orchestrator.start_conversation(db, conv, prof)
                db.refresh(conv)
            new_msgs = orchestrator.handle_message(
                db, conv, prof, text,
                on_delta=lambda t: events.put({"type": "delta", "text": t}))
            events.put({"type": "done", "messages": [_msg_out(m) for m in new_msgs]})
        except Exception:
            log.exception("chat stream failed")
            _save_user_message_after_failure(db, conv_id, text)
            events.put({"type": "error", "detail": "something went wrong, please try again"})
        finally:
            db.close()
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while True:
            ev = events.get()
            if ev is None:
                return
            yield _sse(ev)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/predictions")
def list_predictions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _active_profile(user)
    recs = _prediction_rows(db, [p.id] if p else [])
    count = lambda o: sum(1 for r in recs if r["outcome"] == o)  # noqa: E731
    return {"predictions": recs,
            "aggregate": {"total": len(recs), "happened": count("happened"),
                          "partly": count("partly"), "did_not": count("did_not"),
                          "unsure": count("unsure"),
                          "pending": sum(1 for r in recs if r["outcome"] is None)}}


def _prediction_rows(db: Session, profile_ids: list[int]) -> list[dict]:
    if not profile_ids:
        return []
    return [{
        "id": r.id, "profile_id": r.profile_id, "domain": r.domain, "question": r.question,
        "window_start": _iso(r.window_start), "window_end": _iso(r.window_end),
        "convergence": r.convergence, "created_at": _iso(r.created_at),
        "layer_verdicts": json.loads(r.layer_verdicts) if r.layer_verdicts else None,
        "outcome": r.outcome, "outcome_at": _iso(r.outcome_at),
    } for r in db.query(PredictionRecord)
        .filter(PredictionRecord.profile_id.in_(profile_ids))
        .order_by(PredictionRecord.id).all()]


@app.post("/api/chat/reset")
def chat_reset(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Clear the conversation. Calibration answers are NOT wiped for a chart
    that is pending or failed — otherwise restarting would re-ask the same
    checks and a user could simply answer differently. Only a material birth
    detail edit (or an adopted rectified time) starts calibration over."""
    p = _require_profile(user)
    conv = _profile_conversation(db, p)
    for m in list(conv.messages):
        db.delete(m)
    db.flush()
    conv.pending_event_id = ""
    state = p.calibration_state or "pending"
    if p and state == "uncalibrated":
        conv.state = "rectify"
        text, options = orchestrator.rectify_invite(p)
        orchestrator._add_msg(db, conv, "assistant", text, kind="options",
                              meta={"options": options, "actions": {"Edit birth details": "edit_birth"}})
    elif p and state == "insufficient_history":
        conv.state = "open"
        orchestrator._add_msg(db, conv, "assistant", orchestrator.insufficient_msg(p))
    elif p and state == "pending":
        # keep answered checks; the next history load asks the next unanswered one
        conv.state = "cal_intro"
    else:
        # calibrated/partial: a deliberate fresh start re-runs the checks
        conv.state = "cal_intro"
        if p:
            db.query(CalibrationEvent).filter(CalibrationEvent.profile_id == p.id).delete()
            p.calibration_state = "pending"
            p.predictions_allowed = False
    db.commit()
    return {"reset": True}


# ------------------------------------------------------------- charts

@app.get("/api/chart/{varga}")
def get_chart(varga: str, user: User = Depends(current_user)):
    p = _require_profile(user)
    v = varga.upper()
    facts = orchestrator.chart_facts(p)
    if v not in facts["vargas"]:
        raise HTTPException(404, f"{v} not computed")
    return {"varga": v, "lagna": facts["lagna"], "chart": facts["vargas"][v],
            "fingerprint": p.calc_fingerprint}


@app.get("/api/calibration")
def calibration_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _require_profile(user)
    evs = (db.query(CalibrationEvent)
           .filter(CalibrationEvent.profile_id == p.id).all())
    return {
        "state": p.calibration_state,
        "predictions_allowed": p.predictions_allowed,
        "events": [{
            "event_id": e.event_id, "domain": e.domain,
            "predicted_event": e.predicted_event,
            "window": {"start": e.predicted_window_start, "end": e.predicted_window_end},
            "user_feedback": e.user_feedback, "actual_date": e.actual_date,
            "matched": e.matched,
        } for e in evs],
    }


# ------------------------------------------------------------- tester feedback

FEEDBACK_KINDS = ("text", "analysis", "chart")
REPORTS_PER_HOUR = 10
APP_VERSION = app.version


@app.post("/api/messages/{message_id}/feedback")
def message_feedback(message_id: int, body: FeedbackIn, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    """Thumbs up/down (rating 1/-1) on an assistant message in the caller's own
    conversations; one vote per user per message, changeable; 0 clears it."""
    m = (db.query(Message).join(Conversation, Message.conversation_id == Conversation.id)
         .filter(Message.id == message_id, Conversation.user_id == user.id).first())
    if m is None:
        raise HTTPException(404, "message not found")
    if m.role != "assistant" or m.kind not in FEEDBACK_KINDS:
        raise HTTPException(400, "this message can't be rated")
    fb = (db.query(MessageFeedback)
          .filter(MessageFeedback.message_id == m.id, MessageFeedback.user_id == user.id).first())
    if body.rating == 0:
        if fb is not None:
            db.delete(fb)
        db.commit()
        return {"rating": 0, "comment": ""}
    comment = body.comment.strip() if body.rating < 0 else ""
    if fb is None:
        fb = MessageFeedback(message_id=m.id, user_id=user.id)
        db.add(fb)
    fb.rating, fb.comment, fb.created_at = body.rating, comment, _now()
    db.commit()
    return {"rating": fb.rating, "comment": fb.comment}


@app.post("/api/feedback/report")
def report_problem(body: ReportIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    since = _now().replace(microsecond=0) - timedelta(hours=1)
    recent = (db.query(func.count(ProblemReport.id))
              .filter(ProblemReport.user_id == user.id, ProblemReport.created_at >= since)
              .scalar())
    if recent >= REPORTS_PER_HOUR:
        raise HTTPException(429, "too many reports — please try again later")
    p = _active_profile(user)
    last_ids = []
    if p is not None:
        conv = (db.query(Conversation).filter(Conversation.profile_id == p.id)
                .order_by(Conversation.id.desc()).first())
        if conv is not None:
            last_ids = [i for (i,) in db.query(Message.id)
                        .filter(Message.conversation_id == conv.id)
                        .order_by(Message.id.desc()).limit(10).all()][::-1]
    context = {
        "page": body.page, "client_version": body.app_version, "server_version": APP_VERSION,
        "last_message_ids": last_ids,
        "profile": ({"id": p.id, "relation": p.relation or "self",
                     "calibration_state": p.calibration_state,
                     "predictions_allowed": bool(p.predictions_allowed)} if p else None),
    }
    db.add(ProblemReport(user_id=user.id, text=body.text.strip(),
                         context_json=json.dumps(context)))
    db.commit()
    return {"ok": True}


def _is_admin(user: User) -> bool:
    if user.email.lower() not in settings.ADMIN_EMAILS:
        return False
    # with email delivery configured, an admin address must be verified so that
    # nobody can claim it by registering it first
    return bool(user.email_verified) or not settings.SMTP_HOST


def require_admin(user: User = Depends(current_user)) -> User:
    if not _is_admin(user):
        raise HTTPException(403, "not authorised")
    return user


@app.get("/api/admin/feedback")
def admin_feedback(limit: int = Query(default=100, ge=1, le=500),
                   admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    emails = lambda ids: dict(db.query(User.id, User.email).filter(User.id.in_(ids)).all()) if ids else {}  # noqa: E731
    up = db.query(func.count(MessageFeedback.id)).filter(MessageFeedback.rating > 0).scalar()
    down = db.query(func.count(MessageFeedback.id)).filter(MessageFeedback.rating < 0).scalar()
    reports = (db.query(ProblemReport).order_by(ProblemReport.id.desc()).limit(limit).all())
    downs = (db.query(MessageFeedback).filter(MessageFeedback.rating < 0)
             .order_by(MessageFeedback.id.desc()).limit(limit).all())
    who = emails({r.user_id for r in reports} | {f.user_id for f in downs})
    down_rows = []
    for f in downs:
        m = db.get(Message, f.message_id)
        prev = (db.query(Message).filter(Message.conversation_id == m.conversation_id,
                                         Message.role == "user", Message.id < m.id)
                .order_by(Message.id.desc()).first()) if m else None
        down_rows.append({
            "id": f.id, "created_at": _iso(f.created_at), "user_email": who.get(f.user_id, ""),
            "comment": f.comment or "",
            "message": {"id": m.id, "kind": m.kind, "content": m.content} if m else None,
            "previous_user_message": {"id": prev.id, "content": prev.content} if prev else None,
        })
    return {
        "totals": {"up": up, "down": down, "reports": db.query(func.count(ProblemReport.id)).scalar()},
        "reports": [{"id": r.id, "created_at": _iso(r.created_at),
                     "user_email": who.get(r.user_id, ""), "text": r.text,
                     "context": json.loads(r.context_json or "{}")} for r in reports],
        "down_votes": down_rows,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "llm_provider": settings.LLM_PROVIDER}


# ------------------------------------------------------------- frontend
# Serve the statically-exported Next.js app (frontend/out) with SPA fallback.
# Registered last so every /api/* route above wins.
_FRONTEND_DIR = os.environ.get(
    "JYOTISH_FRONTEND_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "out"))

if os.path.isdir(_FRONTEND_DIR):
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return Response(status_code=404)
        root = os.path.abspath(_FRONTEND_DIR)
        cand = os.path.abspath(os.path.join(root, full_path or "index.html"))
        if os.path.commonpath([root, cand]) != root:       # path traversal guard
            return Response(status_code=404)
        if os.path.isfile(cand):
            return FileResponse(cand)
        if os.path.isfile(cand + ".html"):
            return FileResponse(cand + ".html")
        return FileResponse(os.path.join(root, "index.html"))
