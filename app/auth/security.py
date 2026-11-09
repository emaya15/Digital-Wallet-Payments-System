"""Password / PIN hashing and JWT helpers."""
from datetime import timedelta
from typing import Any, Dict

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.utils.time import utcnow

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.bcrypt_rounds)


def hash_secret(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_secret(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(user_id: int, role: str) -> str:
    expire = utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    claims = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Return the token claims or raise ``JWTError`` (expired / tampered / malformed)."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


__all__ = ["hash_secret", "verify_secret", "create_access_token", "decode_access_token", "JWTError"]
