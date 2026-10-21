from typing import TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.rbac import require_roles
from app.integrations.nextjs import Revalidator
from app.models import ArticleType, Category, Tag, User
from app.repositories.queries import get_record
from app.schemas.content import (
    CategoryCreate,
    CategoryUpdate,
    ClassificationCreate,
    ClassificationUpdate,
)
from app.services.common import advisory_lock, audit, transaction
from app.utils.validation import generated_slug

C = TypeVar("C", bound=Category | Tag | ArticleType)
CLASSIFICATION_LOCK = 7002


async def check_parent(session: AsyncSession, identity: UUID | None, parent: UUID | None) -> None:
    if parent is None:
        return
    ancestors = (
        select(Category.id, Category.parent_id)
        .where(Category.id == parent)
        .cte("ancestors", recursive=True)
    )
    ancestors = ancestors.union_all(
        select(Category.id, Category.parent_id).join(
            ancestors, Category.id == ancestors.c.parent_id
        )
    )
    ids = list((await session.scalars(select(ancestors.c.id))).all())
    if not ids:
        raise APIError(422, "invalid_reference", "Parent category does not exist")
    if identity is not None and identity in ids:
        raise APIError(409, "category_cycle", "Category hierarchy cannot contain cycles")


async def create_classification(
    session: AsyncSession,
    model: type[C],
    actor: User,
    data: ClassificationCreate | CategoryCreate,
    ip: str,
    revalidator: Revalidator,
) -> C:
    require_roles(actor, "admin")
    changes = data.model_dump()
    changes["slug"] = changes.get("slug") or generated_slug(data.name, 180)
    async with transaction(session):
        await advisory_lock(session, CLASSIFICATION_LOCK)
        if model is Category:
            await check_parent(session, None, changes.get("parent_id"))
        record = model(**changes)
        session.add(record)
        await session.flush()
        audit(session, actor, "classification.create", model.__tablename__, record.id, ip)
    await revalidator.notify("classification.create", record.id)
    return record


async def update_classification(
    session: AsyncSession,
    model: type[C],
    actor: User,
    identity: UUID,
    data: ClassificationUpdate | CategoryUpdate,
    ip: str,
    revalidator: Revalidator,
) -> C:
    require_roles(actor, "admin")
    changes = data.model_dump(exclude_unset=True)
    async with transaction(session):
        await advisory_lock(session, CLASSIFICATION_LOCK)
        record = await get_record(session, model, identity, lock=True)
        if model is Category and "parent_id" in changes:
            await check_parent(session, identity, changes["parent_id"])
        for key, value in changes.items():
            setattr(record, key, value)
        await session.flush()
        await session.refresh(record)
        if changes:
            audit(
                session,
                actor,
                "classification.update",
                model.__tablename__,
                record.id,
                ip,
                {"changed_fields": sorted(changes)},
            )
    if changes:
        await revalidator.notify("classification.update", record.id)
    return record


async def delete_classification(
    session: AsyncSession,
    model: type[C],
    actor: User,
    identity: UUID,
    ip: str,
    revalidator: Revalidator,
) -> None:
    require_roles(actor, "admin")
    async with transaction(session):
        await advisory_lock(session, CLASSIFICATION_LOCK)
        record = await get_record(session, model, identity, lock=True)
        audit(session, actor, "classification.delete", model.__tablename__, record.id, ip)
        await session.delete(record)
    await revalidator.notify("classification.delete", identity)
