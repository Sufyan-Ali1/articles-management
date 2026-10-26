import html
import re
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, forbidden, not_found
from app.core.rbac import require_roles
from app.core.security import blocking_limiter
from app.integrations.nextjs import Revalidator
from app.models import Article, ArticleType, Category, Tag, User
from app.repositories.queries import ARTICLE_LOAD, get_article
from app.schemas.content import ArticleCreate, ArticleUpdate
from app.services.classifications import CLASSIFICATION_LOCK
from app.services.common import advisory_lock, audit, transaction
from app.services.media import MEDIA_LOCK, image_urls, reconcile_media
from app.services.users import ADMIN_LOCK
from app.utils.validation import generated_slug, sanitize_html

C = TypeVar("C", bound=Category | Tag | ArticleType)


async def clean_content(value: str) -> str:
    cleaned = await anyio.to_thread.run_sync(sanitize_html, value, limiter=blocking_limiter)
    if not html.unescape(re.sub(r"<[^>]*>", "", cleaned)).strip() and not re.search(
        r"<img\s[^>]*src=", cleaned
    ):
        raise APIError(422, "empty_content", "Article requires content after sanitization")
    return cleaned


async def references(
    session: AsyncSession, model: type[C], ids: list[UUID], *, active: bool = False
) -> list[C]:
    if not ids:
        return []
    rows = list(
        (
            await session.scalars(
                select(model).where(model.id.in_(ids)).execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(rows) != len(ids) or (active and any(not row.is_active for row in rows)):
        raise APIError(
            422,
            "invalid_reference",
            "One or more classifications are missing or inactive",
        )
    return rows


async def validate_published(session: AsyncSession, article: Article) -> None:
    # Lock order is fixed across services; classifications cannot deactivate during publication.
    await advisory_lock(session, ADMIN_LOCK)
    await advisory_lock(session, CLASSIFICATION_LOCK)
    if not article.title.strip() or not article.article_type_id or not article.author_id:
        raise APIError(
            422,
            "publication_invalid",
            "Publication requires title, article type and author",
        )
    author = await session.scalar(
        select(User).where(User.id == article.author_id).execution_options(populate_existing=True)
    )
    if author is None or not author.is_active:
        raise APIError(422, "publication_invalid", "Publication requires an active author")
    await references(session, ArticleType, [article.article_type_id], active=True)
    await references(session, Category, [c.id for c in article.categories], active=True)
    await references(session, Tag, [t.id for t in article.tags], active=True)
    if not article.content_html.strip():
        raise APIError(422, "publication_invalid", "Publication requires article content")


async def apply_relationships(
    session: AsyncSession, article: Article, changes: dict[str, Any]
) -> None:
    if "category_ids" in changes:
        article.categories = await references(session, Category, changes.pop("category_ids"))
    if "tag_ids" in changes:
        article.tags = await references(session, Tag, changes.pop("tag_ids"))
    if "article_type_id" in changes:
        await references(session, ArticleType, [changes["article_type_id"]])


async def create_article(
    session: AsyncSession, actor: User, data: ArticleCreate, ip: str
) -> Article:
    require_roles(actor, "admin", "editor", "author")
    if actor.role == "author" and data.is_featured:
        raise forbidden()
    changes = data.model_dump(by_alias=True)
    changes["slug"] = changes.get("slug") or generated_slug(data.title, 350)
    changes["content_html"] = await clean_content(data.content_html)
    async with transaction(session):
        await advisory_lock(session, MEDIA_LOCK)
        await advisory_lock(session, CLASSIFICATION_LOCK)
        article = Article(author_id=actor.id, status="draft", categories=[], tags=[])
        await apply_relationships(session, article, changes)
        for key, value in changes.items():
            setattr(article, key, value)
        session.add(article)
        await session.flush()
        audit(session, actor, "article.create", "article", article.id, ip)
        await reconcile_media(session, image_urls(article))
        article = await get_article(session, article.id)
    return article


async def update_article(
    session: AsyncSession,
    actor: User,
    identity: UUID,
    data: ArticleUpdate,
    ip: str,
    revalidator: Revalidator,
) -> Article:
    require_roles(actor, "admin", "editor", "author")
    changes = data.model_dump(exclude_unset=True, by_alias=True)
    if "content_html" in changes:
        changes["content_html"] = await clean_content(changes["content_html"])
    async with transaction(session):
        await advisory_lock(session, MEDIA_LOCK)
        article = await get_article(session, identity, lock=True)
        if actor.role == "author":
            if article.author_id != actor.id:
                raise not_found()
            if article.status != "draft":
                raise forbidden()
            if "status" in changes or "is_featured" in changes:
                raise forbidden()
        old_images = image_urls(article)
        old_slug, was_public = article.slug, article.status == "published"
        old_status = article.status
        if was_public or article.status == "scheduled":
            await advisory_lock(session, ADMIN_LOCK)
        await advisory_lock(session, CLASSIFICATION_LOCK)
        if "status" in changes:
            status = changes["status"]
            if status in {"published", "scheduled"} or (
                article.status == "published" and status == "draft"
            ):
                raise APIError(
                    422,
                    "dedicated_workflow_required",
                    "Use the publish, unpublish or schedule endpoint",
                )
        fields = sorted(changes)
        await apply_relationships(session, article, changes)
        for key, value in changes.items():
            setattr(article, key, value)
        if article.status != "scheduled":
            article.scheduled_publish_at = None
        if article.status in {"published", "scheduled"}:
            await validate_published(session, article)
        await session.flush()
        if fields:
            audit(
                session,
                actor,
                "article.update",
                "article",
                article.id,
                ip,
                {
                    "changed_fields": fields,
                    "old_status": old_status,
                    "new_status": article.status,
                },
            )
        await reconcile_media(session, old_images | image_urls(article))
        article = await get_article(session, identity)
    if fields and (was_public or article.status == "published"):
        await revalidator.notify("article.update", article.id, [old_slug, article.slug])
    return article


async def publish_article(
    session: AsyncSession,
    actor: User,
    identity: UUID,
    publish: bool,
    ip: str,
    revalidator: Revalidator,
) -> Article:
    if actor.role not in {"admin", "editor"}:
        raise forbidden()
    changed = False
    async with transaction(session):
        await advisory_lock(session, MEDIA_LOCK)
        article = await get_article(session, identity, lock=True)
        target = "published" if publish else "draft"
        if article.status != target:
            if publish:
                await validate_published(session, article)
                article.published_at = article.published_at or datetime.now(UTC)
            elif article.status != "published":
                raise APIError(
                    409,
                    "invalid_transition",
                    "Only a published article can be unpublished",
                )
            article.scheduled_publish_at = None
            article.status = target
            await session.flush()
            audit(
                session,
                actor,
                "article.publish" if publish else "article.unpublish",
                "article",
                article.id,
                ip,
            )
            article = await get_article(session, identity)
            changed = True
    if changed:
        await revalidator.notify(
            "article.publish" if publish else "article.unpublish",
            article.id,
            [article.slug],
        )
    return article


async def delete_article(
    session: AsyncSession,
    actor: User,
    identity: UUID,
    ip: str,
    revalidator: Revalidator,
) -> None:
    require_roles(actor, "admin")
    async with transaction(session):
        await advisory_lock(session, MEDIA_LOCK)
        article = await get_article(session, identity, lock=True)
        public, slug = article.status == "published", article.slug
        audit(session, actor, "article.delete", "article", identity, ip)
        old_images = image_urls(article)
        await session.delete(article)
        await session.flush()
        await reconcile_media(session, old_images)
    if public:
        await revalidator.notify("article.delete", identity, [slug])


async def public_detail(session: AsyncSession, slug: str) -> Article:
    article = await session.scalar(
        select(Article)
        .where(Article.slug == slug, Article.status == "published")
        .options(*ARTICLE_LOAD)
    )
    if article is None:
        raise not_found()
    return article
