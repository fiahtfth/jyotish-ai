import hmac
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, User

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
               "exp": datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRE_HOURS)}
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
