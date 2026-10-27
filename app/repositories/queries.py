from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.core.errors import APIError, not_found
from app.db.base import Base
from app.models import Article, ArticleType, Category, Tag
from app.schemas.common import ArticleFilters, Pagination, PublicArticleFilters

M = TypeVar("M", bound=Base)
ARTICLE_LOAD = (
    selectinload(Article.categories),
    selectinload(Article.tags),
    selectinload(Article.article_type),
    selectinload(Article.author),
)


async def get_record(
    session: AsyncSession, model: type[M], identity: UUID, *, lock: bool = False
) -> M:
    query = select(model).where(model.id == identity)
    if lock:
        query = query.with_for_update()
    result = await session.scalar(query)
    if result is None:
        raise not_found()
    return result


async def get_article(session: AsyncSession, identity: UUID, *, lock: bool = False) -> Article:
    query = select(Article).where(Article.id == identity).options(*ARTICLE_LOAD)
    if lock:
        query = query.with_for_update()
    result = await session.scalar(query.execution_options(populate_existing=True))
    if result is None:
        raise not_found()
    return result


async def list_records(
    session: AsyncSession,
    model: type[M],
    params: Pagination,
    *,
    query: Select[Any] | None = None,
    allowed: set[str] | None = None,
) -> tuple[list[M], int]:
    allowed = allowed or {"created_at", "updated_at", "name", "slug"}
    field = params.sort.removeprefix("-")
    if field not in allowed:
        raise APIError(422, "invalid_sort", "Unsupported sort field")
    query = query if query is not None else select(model)
    if params.search:
        escaped = params.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        name = getattr(model, "title", None)
        if name is None:
            name = getattr(model, "name", None)
        if name is None:
            name = getattr(model, "topic", None)
        if name is None:
            raise APIError(422, "invalid_search", "Search is not supported here")
        query = query.where(name.ilike(f"%{escaped}%", escape="\\"))
    total = (
        await session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    )
    column = getattr(model, field)
    order = column.desc().nulls_last() if params.sort.startswith("-") else column.asc().nulls_last()
    query = (
        query.order_by(order, model.id)
        .offset((params.page - 1) * params.page_size)
        .limit(params.page_size)
    )
    records = list((await session.scalars(query)).unique().all())
    return records, total


def article_query(
    params: PublicArticleFilters, *, public: bool, user_id: UUID | None = None
) -> Select[Any]:
    query = select(Article).options(
        *ARTICLE_LOAD,
        load_only(
            Article.id,
            Article.title,
            Article.slug,
            Article.excerpt,
            Article.featured_image,
            Article.featured_image_alt,
            Article.author_id,
            Article.created_by_id,
            Article.article_type_id,
            Article.status,
            Article.is_featured,
            Article.view_count,
            Article.published_at,
            Article.scheduled_publish_at,
            Article.created_at,
            Article.updated_at,
            raiseload=True,
        ),
    )
    if public:
        query = query.where(Article.status == "published")
        if isinstance(params, ArticleFilters) and params.status is not None:
            raise APIError(
                422, "invalid_filter", "Status is only available to administrative queries"
            )
    elif isinstance(params, ArticleFilters) and params.status:
        query = query.where(Article.status == params.status)
    if user_id is not None:
        query = query.where(Article.created_by_id == user_id)
    if params.category:
        query = query.where(Article.categories.any(Category.slug == params.category))
    if params.tag:
        query = query.where(Article.tags.any(Tag.slug == params.tag))
    if params.article_type:
        query = query.where(Article.article_type.has(ArticleType.slug == params.article_type))
    if params.is_featured is not None:
        query = query.where(Article.is_featured == params.is_featured)
    if params.published_from:
        query = query.where(Article.published_at >= params.published_from)
    if params.published_to:
        query = query.where(Article.published_at <= params.published_to)
    return query
