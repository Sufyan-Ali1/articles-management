import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.limits import Limit
from app.core.security import create_token
from app.models import RefreshSession, User
from app.schemas.users import Token
from app.services.common import transaction

COOKIE = "blog_refresh"
COOKIE_PATH = "/api/v1/auth"


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def protect(request: Request) -> None:
    # A custom header forces cross-origin browser requests through CORS preflight.
    origin = request.headers.get("origin")
    same_origin = str(request.base_url).rstrip("/")
    if request.headers.get("x-csrf-protection") != "1" or (
        origin and origin != same_origin and origin not in request.app.state.settings.cors_origins
    ):
        raise APIError(403, "csrf_rejected", "Request origin could not be verified")


def cookie(response: Response, raw: str, request: Request, max_age: int | None = None) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        COOKIE,
        raw,
        max_age=max_age if max_age is not None else settings.refresh_session_days * 86400,
        httponly=True,
        secure=settings.environment == "production" or settings.refresh_cookie_samesite == "none",
        samesite=settings.refresh_cookie_samesite,
        path=COOKIE_PATH,
    )
    response.headers["Cache-Control"] = "no-store"


async def issue(session: AsyncSession, user: User, request: Request, response: Response) -> Token:
    settings = request.app.state.settings
    raw = secrets.token_urlsafe(48)
    record = RefreshSession(
        user_id=user.id,
        token_hash=fingerprint(raw),
        password_fingerprint=fingerprint(user.password_hash),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_session_days),
    )
    async with transaction(session):
        session.add(record)
        await session.flush()
    cookie(response, raw, request)
    return Token(
        access_token=create_token(user.id, settings, record.id),
        expires_in=settings.access_token_minutes * 60,
    )


async def refresh(session: AsyncSession, request: Request, response: Response) -> Token:
    protect(request)
    from app.core.middleware import client_ip

    await request.app.state.limiter.check(Limit(f"refresh:{client_ip(request.scope)}", 120, 60))
    raw = request.cookies.get(COOKIE, "")
    settings = request.app.state.settings
    async with transaction(session):
        record = await session.scalar(
            select(RefreshSession)
            .where(RefreshSession.token_hash == fingerprint(raw))
            .with_for_update()
        )
        user = await session.get(User, record.user_id) if record else None
        if (
            not record
            or not user
            or not user.is_active
            or record.expires_at <= datetime.now(UTC)
            or record.password_fingerprint != fingerprint(user.password_hash)
        ):
            raise APIError(401, "unauthorized", "Session expired. Sign in again.")
        raw = secrets.token_urlsafe(48)
        record.token_hash = fingerprint(raw)
        token = Token(
            access_token=create_token(user.id, settings, record.id),
            expires_in=settings.access_token_minutes * 60,
        )
        remaining = max(0, int((record.expires_at - datetime.now(UTC)).total_seconds()))
    # Rotation never extends the absolute session lifetime.
    cookie(response, raw, request, remaining)
    return token


async def revoke(session: AsyncSession, request: Request, response: Response) -> None:
    protect(request)
    async with transaction(session):
        record = await session.scalar(
            select(RefreshSession)
            .where(RefreshSession.token_hash == fingerprint(request.cookies.get(COOKIE, "")))
            .with_for_update()
        )
        if record:
            await session.delete(record)
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.headers["Cache-Control"] = "no-store"
