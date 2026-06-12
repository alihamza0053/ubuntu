"""
Password hashing (bcrypt) and JWT creation/validation.

Uses the `bcrypt` library directly (passlib is unmaintained and breaks
with bcrypt >= 4.1).
"""
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from .config import settings


def _truncate(password: str) -> bytes:
    # bcrypt only uses the first 72 bytes; newer versions raise instead of
    # truncating silently, so truncate explicitly for consistent behavior.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(plain), hashed.encode("utf-8"))
    except ValueError:
        return False  # malformed stored hash


def create_access_token(username: str) -> str:
    """Issue a signed JWT with `sub` = username."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return the username embedded in a valid token, else None."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
