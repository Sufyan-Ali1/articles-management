import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.rbac import require_roles
from app.models import ArticleRequest, User
from app.repositories.queries import get_record
from app.schemas.requests import RequestCreate, RequestUpdate
from app.services.common import audit, transaction


class SubmissionGuard:
    """Bounded, process-local duplicate suppression; never retain raw contact data."""

    def __init__(self, max_keys: int = 10000) -> None:
        self.max_keys = max_keys
        self.entries: dict[str, tuple[float, asyncio.Future[bool]]] = {}
        self.lock = asyncio.Lock()

    async def submit(self, key: str, save: Callable[[], Awaitable[None]]) -> None:
        while True:
            now = time.monotonic()
            async with self.lock:
                self.entries = {
                    k: entry
                    for k, entry in self.entries.items()
                    if not entry[1].done() or entry[0] > now
                }
                existing = self.entries.get(key)
                owner = existing is None
                if owner:
                    if len(self.entries) >= self.max_keys:
                        raise APIError(
                            429,
                            "rate_limited",
                            "Please try again later",
                            headers={"Retry-After": "60"},
                        )
                    future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
                    self.entries[key] = (now + 600, future)
                else:
                    assert existing is not None
                    future = existing[1]
            if not owner:
                if await asyncio.shield(future):
                    return
                continue
            success = False
            try:
                await save()
                success = True
                return
            finally:
                with anyio.CancelScope(shield=True):
                    async with self.lock:
                        if success:
                            self.entries[key] = (time.monotonic() + 600, future)
                        else:
                            self.entries.pop(key, None)
                        future.set_result(success)


async def submit_request(
    session: AsyncSession, data: RequestCreate, ip: str, guard: SubmissionGuard
) -> None:
    if data.website:
        return
    values = data.model_dump(exclude={"website"})
    normalized = json.dumps(
        {k: v.casefold() if isinstance(v, str) else v for k, v in values.items()}, sort_keys=True
    )
    fingerprint = hashlib.sha256((ip + "\0" + normalized).encode()).hexdigest()

    async def save() -> None:
        async with transaction(session):
            session.add(ArticleRequest(**values, status="pending"))

    await guard.submit(fingerprint, save)


async def review_request(
    session: AsyncSession, actor: User, identity: UUID, data: RequestUpdate, ip: str
) -> ArticleRequest:
    require_roles(actor, "admin", "editor")
    async with transaction(session):
        record = await get_record(session, ArticleRequest, identity, lock=True)
        changes = {
            key: value
            for key, value in data.model_dump(exclude_unset=True).items()
            if getattr(record, key) != value
        }
        old_status = record.status
        for key, value in changes.items():
            setattr(record, key, value)
        if changes:
            record.reviewed_by = actor.id
            await session.flush()
            await session.refresh(record)
            audit(
                session,
                actor,
                "article_request.review",
                "article_request",
                identity,
                ip,
                {
                    "changed_fields": sorted(changes),
                    "old_status": old_status,
                    "new_status": record.status,
                },
            )
    return record


async def delete_request(session: AsyncSession, actor: User, identity: UUID, ip: str) -> None:
    require_roles(actor, "admin")
    async with transaction(session):
        record = await get_record(session, ArticleRequest, identity, lock=True)
        audit(session, actor, "article_request.delete", "article_request", identity, ip)
        await session.delete(record)
