from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, forbidden
from app.core.security import hash_password
from app.integrations.nextjs import Revalidator
from app.models import User
from app.repositories.queries import get_record
from app.schemas.users import UserCreate, UserUpdate
from app.services.common import advisory_lock, audit, transaction

ADMIN_LOCK = 7001


async def create_user(session: AsyncSession, actor: User, data: UserCreate, ip: str) -> User:
    encoded = await hash_password(data.password.get_secret_value())
    async with transaction(session):
        await advisory_lock(session, ADMIN_LOCK)
        await session.refresh(actor)
        if actor.role != "admin" or not actor.is_active:
            raise forbidden()
        user = User(**data.model_dump(exclude={"password"}), password_hash=encoded)
        session.add(user)
        await session.flush()
        audit(session, actor, "user.create", "user", user.id, ip)
    return user


async def update_user(
    session: AsyncSession,
    actor: User,
    identity: UUID,
    data: UserUpdate,
    ip: str,
    revalidator: Revalidator,
) -> User:
    changes = data.model_dump(exclude_unset=True, exclude={"password"})
    if data.password is not None:
        changes["password_hash"] = await hash_password(data.password.get_secret_value())
    async with transaction(session):
        await advisory_lock(session, ADMIN_LOCK)
        await session.refresh(actor)
        if actor.role != "admin" or not actor.is_active:
            raise forbidden()
        user = await get_record(session, User, identity, lock=True)
        await session.refresh(user)
        if (
            user.role == "admin"
            and user.is_active
            and (changes.get("role", user.role) != "admin" or changes.get("is_active") is False)
        ):
            count = await session.scalar(
                select(func.count()).select_from(User).where(User.role == "admin", User.is_active)
            )
            if count == 1:
                raise APIError(
                    409, "last_admin", "Cannot deactivate or demote the last active administrator"
                )
        for key, value in changes.items():
            setattr(user, key, value)
        await session.flush()
        await session.refresh(user)
        if changes:
            audit(
                session,
                actor,
                "user.update",
                "user",
                user.id,
                ip,
                {
                    "changed_fields": sorted(
                        "password" if k == "password_hash" else k for k in changes
                    )
                },
            )
    if "name" in changes:
        await revalidator.notify("user.update", user.id)
    return user
