import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .db import AuthToken, User, _utcnow, get_db

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(p: str) -> str:
    return pwd.hash(p)


def verify_password(p: str, h: str) -> bool:
    try:
        return pwd.verify(p, h)
    except Exception:
        return False


def create_token(user: User) -> str:
    payload = {"sub": str(user.id), "nonce": user.token_nonce,
               "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings.JWT_SECRET,
                             algorithms=[settings.JWT_ALGORITHM])
        uid = int(payload["sub"])
        nonce = payload["nonce"]
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    user = db.get(User, uid)
    if not user or not isinstance(nonce, str) or not user.token_nonce \
            or not hmac.compare_digest(nonce, user.token_nonce):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return user


# ---------------------------------------------------------- emailed tokens

TOKEN_TTL = {"reset": timedelta(hours=1), "verify": timedelta(hours=48)}


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_auth_token(db: Session, user: User, purpose: str) -> str:
    """Create a single-use token (only its hash is stored); older unused tokens
    of the same purpose are revoked. Caller commits."""
    now = _utcnow()
    for old in db.query(AuthToken).filter(
            AuthToken.user_id == user.id, AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None)).all():
        old.used_at = now
    raw = secrets.token_urlsafe(32)
    db.add(AuthToken(user_id=user.id, purpose=purpose, token_hash=_hash_token(raw),
                     expires_at=now + TOKEN_TTL[purpose]))
    return raw


def consume_auth_token(db: Session, raw: str, purpose: str) -> User | None:
    """Validate and burn a token. Returns its user, or None if unknown, wrong
    purpose, expired or already used. The burn is an atomic conditional UPDATE,
    so a token can't be redeemed twice by concurrent requests. Caller commits."""
    now = _utcnow()
    rec = db.query(AuthToken).filter(AuthToken.token_hash == _hash_token(raw),
                                     AuthToken.purpose == purpose).first()
    if rec is None or rec.used_at is not None or rec.expires_at < now:
        return None
    burned = db.query(AuthToken).filter(
        AuthToken.id == rec.id, AuthToken.used_at.is_(None)
    ).update({"used_at": now}, synchronize_session=False)
    if burned != 1:
        return None
    return db.get(User, rec.user_id)
