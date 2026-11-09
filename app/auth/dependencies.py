"""FastAPI authentication / authorisation dependencies."""
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import JWTError, decode_access_token
from app.database import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def user_from_token(db: Session, token: str) -> User:
    """Resolve a JWT to an active user (shared by HTTP and WebSocket auth)."""
    try:
        claims = decode_access_token(token)
        user_id = int(claims["sub"])
    except (JWTError, KeyError, ValueError, TypeError):
        raise _unauthorized("Invalid or expired token")
    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized("Invalid or expired token")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")
    return user


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise _unauthorized()
    return user_from_token(db, credentials.credentials)


def require_roles(*roles: str):
    """Dependency factory: only users whose role is in ``roles`` may proceed."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
        return user

    return dependency
