"""
Shared FastAPI dependencies: current-user resolution for both HTTP
routes (Authorization: Bearer header) and WebSocket connections
(?token= query parameter).
"""
from fastapi import Depends, HTTPException, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import SessionLocal, get_db
from .models import User
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the user from a Bearer token; 401 on any failure."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = decode_access_token(credentials.credentials)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


async def authenticate_websocket(websocket: WebSocket) -> User | None:
    """
    Authenticate a WebSocket connection via its ?token= query parameter.

    Returns the User on success. On failure the socket is closed with
    policy-violation code 1008 and None is returned — callers must bail out.
    """
    token = websocket.query_params.get("token")
    username = decode_access_token(token) if token else None
    if username is None:
        await websocket.close(code=1008, reason="Invalid or missing token")
        return None

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
    finally:
        db.close()

    if user is None:
        await websocket.close(code=1008, reason="Unknown user")
        return None
    return user
