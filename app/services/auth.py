import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import APIError
from app.core.limits import Limit, RateLimiter
from app.core.security import verify_password
from app.models import User
from app.schemas.users import Login
from app.services.common import audit, transaction


async def login(
    session: AsyncSession,
    data: Login,
    settings: Settings,
    limiter: RateLimiter,
    dummy_hash: str,
    ip: str,
) -> User:
    key = hashlib.sha256(data.email.encode()).hexdigest()
    await limiter.check(
        Limit(f"login:{ip}:{key}", settings.login_account_per_minute, 60),
    )
    user = await session.scalar(select(User).where(User.email == data.email))
    valid = await verify_password(
        user.password_hash if user else dummy_hash, data.password.get_secret_value()
    )
    if user is None or not valid or not user.is_active:
        logging.getLogger(__name__).info("authentication.login_failed")
        raise APIError(
            401,
            "invalid_credentials",
            "Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    async with transaction(session):
        audit(session, user, "auth.login", "user", user.id, ip)
    return user
