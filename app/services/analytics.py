from typing import Any
from urllib.parse import urlencode

from sqlalchemy import String, cast, func, select, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, not_found
from app.core.rbac import require_roles
from app.models import Article, ArticleViewEvent, TrackingLink, TrafficSource, User
from app.repositories.queries import get_record
from app.schemas.analytics import (
    AnalyticsFilters,
    AnalyticsReport,
    AnalyticsRow,
    ArticleViewCreate,
    TrackingDestination,
    TrackingLinkCreate,
    TrackingLinkResponse,
    UtmLinkCreate,
    UtmLinkResponse,
    UtmParameters,
)
from app.services.common import advisory_lock, audit, transaction
from app.services.traffic_sources import SOURCE_LOCK, match_referrer


async def create_utm_link(
    session: AsyncSession, actor: User, data: UtmLinkCreate
) -> UtmLinkResponse:
    require_roles(actor, "admin", "editor")
    source = await session.scalar(
        select(TrafficSource).where(
            TrafficSource.id == data.source_id, TrafficSource.is_active.is_(True)
        )
    )
    if source is None:
        raise APIError(422, "invalid_source", "Select an active configured traffic source")
    article = await get_record(session, Article, data.article_id)
    if article.status != "published":
        raise APIError(409, "invalid_transition", "Tracking URLs require a published article")
    utm = UtmParameters(
        utm_source=source.slug,
        utm_medium=data.medium,
        utm_campaign=data.campaign,
        utm_content=data.content,
    )
    return UtmLinkResponse(
        article_slug=article.slug,
        relative_url=f"/articles/{article.slug}?{urlencode(utm.model_dump(exclude_none=True))}",
        **utm.model_dump(),
    )


async def create_link(
    session: AsyncSession, actor: User, data: TrackingLinkCreate, ip: str
) -> TrackingLink:
    require_roles(actor, "admin", "editor")
    async with transaction(session):
        await advisory_lock(session, SOURCE_LOCK)
        source = await session.scalar(
            select(TrafficSource).where(
                TrafficSource.id == data.source_id
                if data.source_id
                else TrafficSource.slug == data.source,
                TrafficSource.is_active.is_(True),
            )
        )
        if source is None or (data.source is not None and source.slug != data.source):
            raise APIError(422, "invalid_source", "Select an active configured traffic source")
        article = await get_record(session, Article, data.article_id, lock=True)
        if article.status != "published":
            raise APIError(409, "invalid_transition", "Tracking links require a published article")
        link = TrackingLink(**{**data.model_dump(), "source": source.slug, "source_id": source.id})
        session.add(link)
        await session.flush()
        audit(session, actor, "tracking_link.create", "tracking_link", link.id, ip)
        await session.refresh(link)
    return link


async def resolve_link(session: AsyncSession, code: str) -> TrackingDestination:
    result = (
        await session.execute(
            select(TrackingLink, Article.slug)
            .join(Article, Article.id == TrackingLink.article_id)
            .join(TrafficSource, TrafficSource.id == TrackingLink.source_id)
            .where(
                TrackingLink.code == code,
                TrackingLink.is_active.is_(True),
                TrafficSource.is_active.is_(True),
                Article.status == "published",
            )
        )
    ).one_or_none()
    if result is None:
        raise not_found()
    link, slug = result
    return TrackingDestination(
        **{**TrackingLinkResponse.model_validate(link).model_dump(), "article_slug": slug}
    )


async def record_view(session: AsyncSession, data: ArticleViewCreate) -> None:
    async with transaction(session):
        # Row locking serializes against unpublication/deletion and keeps count + event atomic.
        article = await session.scalar(
            select(Article)
            .where(Article.slug == data.article_slug, Article.status == "published")
            .with_for_update()
        )
        if article is None:
            raise not_found()
        values: dict[str, Any] = {
            "event_id": data.event_id,
            "session_id": data.session_id,
            "article_id": article.id,
            "referrer_domain": data.referrer_domain,
            "source": data.referrer_domain or "direct_or_unknown",
            "medium": "referral" if data.referrer_domain else "direct",
        }
        if data.tracking_link_id:
            # Disabled links stop new redirects; already attributed sessions remain measurable.
            link = await session.get(TrackingLink, data.tracking_link_id)
            if link is None:
                raise APIError(422, "invalid_tracking_link", "Unknown tracking link")
            values.update(
                source_id=link.source_id,
                tracking_link_id=link.id,
                source=link.source,
                medium=link.medium,
                campaign=link.campaign,
                content=link.content,
            )
        elif data.utm_source:
            # Explicit campaign attribution takes precedence over the referring hostname.
            # Unregistered sources remain visible in grouped reports as unassigned traffic.
            source = await session.scalar(
                select(TrafficSource).where(
                    TrafficSource.slug == data.utm_source, TrafficSource.is_active.is_(True)
                )
            )
            values.update(
                source_id=source.id if source else None,
                source=data.utm_source,
                medium=data.utm_medium or "social",
                campaign=data.utm_campaign,
                content=data.utm_content,
            )
        elif data.referrer_domain:
            source = await match_referrer(session, data.referrer_domain)
            if source is not None:
                values.update(source_id=source.id, source=source.slug)
        inserted = await session.scalar(
            insert(ArticleViewEvent)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[ArticleViewEvent.event_id])
            .returning(ArticleViewEvent.id)
        )
        if inserted is not None:
            await session.execute(
                update(Article)
                .where(Article.id == article.id)
                .values(view_count=Article.view_count + 1, updated_at=Article.updated_at)
            )


async def report(session: AsyncSession, params: AnalyticsFilters) -> AnalyticsReport:
    event = ArticleViewEvent
    conditions = [event.created_at >= params.start, event.created_at < params.end]
    for field in ("article_id", "source", "campaign", "tracking_link_id"):
        value = getattr(params, field)
        if value is not None:
            conditions.append(getattr(event, field) == value)
    # A repeatable snapshot keeps totals and paginated groups consistent within this request.
    base = select(event).where(*conditions).cte("filtered_events")
    key = {
        "source": base.c.source,
        "article": cast(base.c.article_id, String),
        "campaign": func.coalesce(base.c.campaign, "(none)"),
        "link": func.coalesce(cast(base.c.tracking_link_id, String), "(none)"),
        "day": func.to_char(func.timezone("UTC", base.c.created_at), "YYYY-MM-DD"),
    }[params.group_by]
    grouped = (
        select(
            key.label("key"),
            func.count().label("views"),
            func.count(func.distinct(base.c.session_id)).label("sessions"),
        )
        .group_by(key)
        .cte("groups")
    )
    totals = (
        select(
            func.count().label("views"),
            func.count(func.distinct(base.c.session_id)).label("sessions"),
        )
        .select_from(base)
        .cte("totals")
    )
    # One SQL statement for stable totals even with concurrent incoming events, including empty pages.
    page = (
        select(grouped)
        .order_by(grouped.c.views.desc(), grouped.c.key)
        .offset((params.page - 1) * params.page_size)
        .limit(params.page_size)
        .cte("page")
    )
    rows = (
        (
            await session.execute(
                select(
                    totals.c.views,
                    totals.c.sessions,
                    select(func.count())
                    .select_from(grouped)
                    .scalar_subquery()
                    .label("total_groups"),
                    page.c.key,
                    page.c.views.label("group_views"),
                    page.c.sessions.label("group_sessions"),
                ).select_from(totals.outerjoin(page, true()))
            )
        )
        .mappings()
        .all()
    )
    first = rows[0]
    return AnalyticsReport(
        views=first["views"],
        sessions=first["sessions"],
        total_groups=first["total_groups"],
        groups=[
            AnalyticsRow(key=r["key"], views=r["group_views"], sessions=r["group_sessions"])
            for r in rows
            if r["key"] is not None
        ],
        page=params.page,
        page_size=params.page_size,
    )
