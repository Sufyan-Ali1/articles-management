from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.limits import Limit
from app.core.rbac import require_roles
from app.core.security import decode_token
from app.db.session import get_session
from app.models import RefreshSession, User
from app.services.sessions import fingerprint

Session = Annotated[AsyncSession, Depends(get_session)]
bearer = HTTPBearer(auto_error=False)


async def current_user(
    request: Request,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise APIError(
            401,
            "unauthorized",
            "Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials, request.app.state.settings)
    user = await session.get(User, UUID(payload["sub"]))
    valid_session = True
    if "sid" in payload:
        try:
            record = await session.get(RefreshSession, UUID(payload["sid"]))
        except (ValueError, TypeError):
            record = None
        valid_session = bool(
            record
            and user
            and record.user_id == user.id
            and record.expires_at > datetime.now(UTC)
            and record.password_fingerprint == fingerprint(user.password_hash)
        )
    if user is None or not user.is_active or not valid_session:
        raise APIError(
            401,
            "unauthorized",
            "Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        await request.app.state.limiter.check(
            Limit(
                f"mutation:{user.id}",
                request.app.state.settings.mutations_per_minute,
                60,
            )
        )
    return user


Actor = Annotated[User, Depends(current_user)]


async def administrator(user: Actor) -> User:
    require_roles(user, "admin")
    return user


async def reviewer(user: Actor) -> User:
    require_roles(user, "admin", "editor")
    return user


Admin = Annotated[User, Depends(administrator)]
Reviewer = Annotated[User, Depends(reviewer)]


async def optional_user(
    request: Request,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User | None:
    if credentials is None:
        return None
    return await current_user(request, session, credentials)


OptionalActor = Annotated[User | None, Depends(optional_user)]


def classification_access(include_inactive: bool, actor: User | None) -> None:
    if include_inactive:
        if actor is None:
            raise APIError(
                401,
                "unauthorized",
                "Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        require_roles(actor, "admin")


async def public_api_access(
    request: Request,
    api_user: Annotated[
        str | None,
        Depends(APIKeyHeader(name="X-API-User", scheme_name="APIUser", auto_error=False)),
    ],
    api_key: Annotated[
        str | None, Depends(APIKeyHeader(name="X-API-Key", scheme_name="APIKey", auto_error=False))
    ],
) -> None:
    from app.core.api_consumer import valid_api_consumer

    settings = request.app.state.settings
    if not settings.api_user or not settings.api_key:
        raise APIError(
            503,
            "api_access_unconfigured",
            "API access is not configured",
            headers={"Cache-Control": "no-store"},
        )
    if not valid_api_consumer(settings, api_user, api_key):
        raise APIError(
            401,
            "api_access_denied",
            "Valid API credentials are required",
            headers={"Cache-Control": "no-store"},
        )


async def public_or_staff_access(
    request: Request,
    actor: OptionalActor,
    api_user: Annotated[
        str | None,
        Depends(APIKeyHeader(name="X-API-User", scheme_name="APIUser", auto_error=False)),
    ],
    api_key: Annotated[
        str | None, Depends(APIKeyHeader(name="X-API-Key", scheme_name="APIKey", auto_error=False))
    ],
) -> None:
    if actor is None:
        await public_api_access(request, api_user, api_key)
