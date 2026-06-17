"""
Auth routes: login (JWT issuance, rate-limited) and current-user lookup.
"""
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user, require_admin
from pydantic import BaseModel

from ..models import User
from ..permissions import (TABS, parse_permissions, serialize_permissions)
from ..schemas import (DetailResponse, LoginRequest, PasswordReset,
                       TokenResponse, UserCreate, UserOut, UserUpdate)
from ..security import create_access_token, hash_password, verify_password


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, username=u.username, is_admin=bool(u.is_admin),
                   permissions=parse_permissions(u.permissions))

# In-memory login rate limiter: client_ip -> [attempt timestamps].
# Fine for a single-process, single-admin panel.
_attempts: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    window = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    _attempts[ip] = [t for t in _attempts[ip] if now - t < window]
    if len(_attempts[ip]) >= settings.LOGIN_RATE_LIMIT_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Try again in {window} seconds.",
        )
    _attempts[ip].append(now)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Verify credentials and return a JWT."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    user = db.query(User).filter(User.username == body.username).first()
    # Same error for unknown user / wrong password (no username enumeration)
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    return TokenResponse(access_token=create_access_token(user.username))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user (used by the frontend on app load)."""
    return _user_out(current_user)


# ---------------------------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------------------------
@router.get("/permissions")
def permission_catalog(_: User = Depends(require_admin)):
    """The list of tabs an admin can grant (key + label)."""
    return [{"key": k, "label": label} for k, label in TABS]


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [_user_out(u) for u in db.query(User).order_by(User.id).all()]


@router.post("/users", response_model=UserOut)
def create_user(body: UserCreate, _: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    username = body.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be ≥ 3 characters")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be ≥ 8 characters")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="That username already exists")
    user = User(
        username=username,
        hashed_password=hash_password(body.password),
        is_admin=body.is_admin,
        permissions="" if body.is_admin else serialize_permissions(body.permissions),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate,
                current_user: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.is_admin is not None:
        # Don't let an admin strip their own admin rights (lock-out guard)
        if user.id == current_user.id and not body.is_admin:
            raise HTTPException(status_code=400, detail="You can't remove your own admin rights")
        user.is_admin = body.is_admin
    if body.permissions is not None:
        user.permissions = serialize_permissions(body.permissions)
    if user.is_admin:
        user.permissions = ""   # admins implicitly have everything
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/users/{user_id}/password", response_model=DetailResponse)
def reset_user_password(user_id: int, body: PasswordReset,
                        _: User = Depends(require_admin),
                        db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be ≥ 8 characters")
    user.hashed_password = hash_password(body.new_password)
    db.commit()
    return DetailResponse(detail=f"Password reset for {user.username}")


@router.delete("/users/{user_id}", response_model=DetailResponse)
def delete_user(user_id: int, current_user: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't delete yourself")
    if user.is_admin and db.query(User).filter(User.is_admin == True).count() <= 1:  # noqa: E712
        raise HTTPException(status_code=400, detail="Can't delete the last admin")
    db.delete(user)
    db.commit()
    return DetailResponse(detail=f"Deleted {user.username}")


@router.post("/change-password", response_model=DetailResponse)
def change_password(body: PasswordChange,
                    current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Change the admin password after verifying the current one."""
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    current_user.hashed_password = hash_password(body.new_password)
    db.commit()
    return DetailResponse(detail="Password changed")
