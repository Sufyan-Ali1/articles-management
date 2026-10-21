from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.limits import Limit
from app.core.rbac import require_roles
from app.core.security import decode_token
from app.db.session import get_session
from app.models import User

Session = Annotated[AsyncSession, Depends(get_session)]
bearer = HTTPBearer(auto_error=False)


async def current_user(
    request: Request,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise APIError(
            401, "unauthorized", "Authentication required", headers={"WWW-Authenticate": "Bearer"}
        )
    payload = decode_token(credentials.credentials, request.app.state.settings)
    user = await session.get(User, UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise APIError(
            401,
            "unauthorized",
            "Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        await request.app.state.limiter.check(
            Limit(f"mutation:{user.id}", request.app.state.settings.mutations_per_minute, 60)
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
