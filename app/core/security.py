import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import anyio
import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings
from app.core.errors import APIError

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, type=Type.ID)
# This hash is not an account credential. Generated once at startup off the event loop.
blocking_limiter = anyio.CapacityLimiter(2)


async def hash_password(password: str) -> str:
    return await anyio.to_thread.run_sync(hasher.hash, password, limiter=blocking_limiter)


async def verify_password(encoded: str, password: str) -> bool:
    def verify() -> bool:
        try:
            return hasher.verify(encoded, password)
        except (VerificationError, InvalidHashError):
            return False

    return await anyio.to_thread.run_sync(verify, limiter=blocking_limiter)


def create_token(user_id: UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        UUID(payload["sub"])
        return payload
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        logging.getLogger(__name__).info("authentication.invalid_token")
        raise APIError(
            401,
            "unauthorized",
            "Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
