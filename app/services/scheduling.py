"""Database-backed schedules survive restarts and are safe across API workers."""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import APIError
from app.core.rbac import require_roles
from app.integrations.nextjs import Revalidator
from app.models import AdminLog, Article, User
from app.repositories.queries import get_article
from app.services.articles import validate_published
from app.services.common import advisory_lock, audit, transaction
from app.services.media import MEDIA_LOCK

logger = logging.getLogger(__name__)


async def schedule_article(
    session: AsyncSession, actor: User, identity: UUID, when: datetime | None, ip: str
) -> Article:
    require_roles(actor, "admin", "editor")
    async with transaction(session):
        await advisory_lock(session, MEDIA_LOCK)
        article = await get_article(session, identity, lock=True)
        if when is None:
            if article.status != "scheduled":
                raise APIError(
                    409, "invalid_transition", "Only a scheduled article can be cancelled"
                )
            article.status = "draft"
            article.scheduled_publish_at = None
        else:
            if when.tzinfo is None or when.utcoffset() is None or when <= datetime.now(UTC):
                raise APIError(
                    422, "invalid_schedule", "Schedule requires a future time with timezone"
                )
            if article.status not in {"draft", "scheduled"}:
                raise APIError(
                    409, "invalid_transition", "Only draft or scheduled articles can be scheduled"
                )
            await validate_published(session, article)
            article.status = "scheduled"
            article.scheduled_publish_at = when.astimezone(UTC)
        audit(
            session,
            actor,
            "article.schedule" if when else "article.schedule_cancel",
            "article",
            identity,
            ip,
            {"scheduled_publish_at": when.isoformat() if when else None},
        )
        await session.flush()
        article = await get_article(session, identity)
    return article


async def publish_due_articles(
    factory: async_sessionmaker[AsyncSession], revalidator: Revalidator
) -> int:
    async with factory() as session:
        identities = list(
            (
                await session.scalars(
                    select(Article.id)
                    .where(
                        Article.status == "scheduled",
                        Article.scheduled_publish_at <= datetime.now(UTC),
                    )
                    .order_by(Article.scheduled_publish_at, Article.id)
                    .limit(100)
                )
            ).all()
        )
    published = 0
    for identity in identities:
        try:
            async with factory() as session:
                async with transaction(session):
                    # Match manual publication's lock order; recheck after concurrent cancellation.
                    await advisory_lock(session, MEDIA_LOCK)
                    article = await get_article(session, identity, lock=True)
                    now = datetime.now(UTC)
                    if (
                        article.status != "scheduled"
                        or article.scheduled_publish_at is None
                        or article.scheduled_publish_at > now
                    ):
                        continue
                    await validate_published(session, article)
                    article.status = "published"
                    article.published_at = article.published_at or now
                    article.scheduled_publish_at = None
                    session.add(
                        AdminLog(
                            action="article.publish",
                            entity_type="article",
                            entity_id=article.id,
                            details={"scheduled": True},
                        )
                    )
                    slug = article.slug
            published += 1
            await revalidator.notify("article.publish", identity, [slug])
        except APIError as exc:
            # Invalid references/authors can be repaired; keep the schedule for retry.
            logger.warning("article.schedule_blocked entity_id=%s code=%s", identity, exc.code)
        except Exception:
            logger.error("article.schedule_failed entity_id=%s", identity)
    return published


async def article_scheduler_worker(
    factory: async_sessionmaker[AsyncSession], settings: Settings, revalidator: Revalidator
) -> None:
    while True:
        try:
            await publish_due_articles(factory, revalidator)
        except Exception:
            logger.error("article.scheduler_poll_failed")
        await asyncio.sleep(settings.article_scheduler_interval_seconds)
