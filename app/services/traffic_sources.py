from uuid import UUID

from sqlalchemy import func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.rbac import require_roles
from app.models import Article, ArticleViewEvent, TrackingLink, TrafficSource, User
from app.repositories.queries import get_record
from app.schemas.analytics import (
    SourceCounts,
    TrafficOverview,
    TrafficOverviewFilters,
    TrafficSourceCreate,
    TrafficSourceResponse,
    TrafficSourceUpdate,
)
from app.services.common import advisory_lock, audit, transaction

SOURCE_LOCK = 71008


async def validate_domains(
    session: AsyncSession, domains: list[str], excluding: UUID | None = None
) -> None:
    if not domains:
        return
    query = (
        select(TrafficSource).where(TrafficSource.id != excluding)
        if excluding
        else select(TrafficSource)
    )
    sources = (await session.scalars(query)).all()
    for source in sources:
        if any(
            a == b or a.endswith("." + b) or b.endswith("." + a)
            for a in domains
            for b in source.referrer_domains
        ):
            raise APIError(
                409, "domain_in_use", "A referrer domain overlaps another traffic source"
            )


async def save_source(
    session: AsyncSession,
    actor: User,
    data: TrafficSourceCreate | TrafficSourceUpdate,
    ip: str,
    identity: UUID | None = None,
) -> TrafficSource:
    require_roles(actor, "admin")
    async with transaction(session):
        await advisory_lock(session, SOURCE_LOCK)
        values = data.model_dump(exclude_unset=identity is not None)
        if "referrer_domains" in values:
            await validate_domains(session, values["referrer_domains"], identity)
        if identity:
            row = await get_record(session, TrafficSource, identity, lock=True)
            for key, value in values.items():
                setattr(row, key, value)
        else:
            row = TrafficSource(**values)
            session.add(row)
        await session.flush()
        audit(
            session,
            actor,
            "traffic_source.update" if identity else "traffic_source.create",
            "traffic_source",
            row.id,
            ip,
        )
        await session.refresh(row)
    return row


async def delete_source(session: AsyncSession, actor: User, identity: UUID, ip: str) -> None:
    require_roles(actor, "admin")
    async with transaction(session):
        await advisory_lock(session, SOURCE_LOCK)
        row = await get_record(session, TrafficSource, identity, lock=True)
        links = await session.scalar(
            select(TrackingLink.id).where(TrackingLink.source_id == identity).limit(1)
        )
        events = await session.scalar(
            select(ArticleViewEvent.id).where(ArticleViewEvent.source_id == identity).limit(1)
        )
        if links or events:
            raise APIError(
                409,
                "source_in_use",
                "This source has links or recorded visits. Deactivate it to preserve attribution.",
            )
        audit(session, actor, "traffic_source.delete", "traffic_source", identity, ip)
        await session.delete(row)


async def match_referrer(session: AsyncSession, domain: str | None) -> TrafficSource | None:
    if domain is None:
        return None
    labels = domain.lower().split(".")
    candidates = [".".join(labels[i:]) for i in range(len(labels) - 1)]
    if not candidates:
        return None
    return await session.scalar(
        select(TrafficSource).where(
            TrafficSource.is_active.is_(True),
            or_(
                *(TrafficSource.referrer_domains.contains([candidate]) for candidate in candidates)
            ),
        )
    )


async def source_overview(session: AsyncSession, params: TrafficOverviewFilters) -> TrafficOverview:
    if params.article_id:
        await get_record(session, Article, params.article_id)
    event = ArticleViewEvent
    all_events = select(event.source_id, event.session_id, event.created_at)
    article_totals = select(func.coalesce(func.sum(Article.view_count), 0))
    if params.article_id:
        all_events = all_events.where(event.article_id == params.article_id)
        article_totals = article_totals.where(Article.id == params.article_id)
    all_events_cte = all_events.cte("all_events")
    filtered = select(all_events_cte)
    if params.start:
        filtered = filtered.where(all_events_cte.c.created_at >= params.start)
    if params.end:
        filtered = filtered.where(all_events_cte.c.created_at < params.end)
    visits = filtered.cte("visits")
    grouped = (
        select(
            visits.c.source_id,
            func.count().label("views"),
            func.count(func.distinct(visits.c.session_id)).label("sessions"),
        )
        .group_by(visits.c.source_id)
        .cte("counts")
    )
    totals = (
        select(
            func.count().label("views"),
            func.count(func.distinct(visits.c.session_id)).label("sessions"),
            func.count().filter(visits.c.source_id.is_(None)).label("unassigned_views"),
            func.count(func.distinct(visits.c.session_id))
            .filter(visits.c.source_id.is_(None))
            .label("unassigned_sessions"),
        )
        .select_from(visits)
        .cte("totals")
    )
    statement = (
        select(
            TrafficSource,
            grouped.c.views.label("source_views"),
            grouped.c.sessions.label("source_sessions"),
            totals.c.views,
            totals.c.sessions,
            totals.c.unassigned_views,
            totals.c.unassigned_sessions,
            article_totals.scalar_subquery().label("lifetime_views"),
            select(func.count())
            .select_from(all_events_cte)
            .scalar_subquery()
            .label("recorded_views"),
        )
        .select_from(
            totals.outerjoin(TrafficSource, true()).outerjoin(
                grouped, TrafficSource.id == grouped.c.source_id
            )
        )
        .order_by(TrafficSource.name, TrafficSource.id)
    )
    rows = (await session.execute(statement)).all()
    first = rows[0]
    sources = [
        SourceCounts(
            **TrafficSourceResponse.model_validate(row.TrafficSource).model_dump(),
            views=row.source_views or 0,
            sessions=row.source_sessions or 0,
        )
        for row in rows
        if row.TrafficSource is not None
    ]
    return TrafficOverview(
        views=first.views,
        sessions=first.sessions,
        lifetime_views=first.lifetime_views,
        legacy_views=max(0, first.lifetime_views - first.recorded_views),
        sources=sources,
        unassigned_views=first.unassigned_views,
        unassigned_sessions=first.unassigned_sessions,
    )
