from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import anyio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models import AdminLog, User


@asynccontextmanager
async def transaction(session: AsyncSession) -> AsyncIterator[None]:
    """Own the request session's transaction, including authentication's initial read."""
    try:
        yield
        await session.commit()
    except IntegrityError:
        with anyio.CancelScope(shield=True):
            await session.rollback()
        raise APIError(
            409,
            "integrity_conflict",
            "A unique value or referenced resource conflicts with this change",
        ) from None
    except BaseException:
        with anyio.CancelScope(shield=True):
            await session.rollback()
        raise


async def advisory_lock(session: AsyncSession, key: int) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def audit(
    session: AsyncSession,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: UUID,
    ip: str,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AdminLog(
            user_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip,
            details=details,
        )
    )
