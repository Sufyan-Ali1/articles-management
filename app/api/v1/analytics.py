import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app.api.dependencies import Admin, Reviewer, Session, public_api_access
from app.core.errors import APIError
from app.core.limits import Limit
from app.core.middleware import client_ip
from app.models import TrackingLink, TrafficSource
from app.repositories.queries import get_record, list_records
from app.schemas.analytics import (
    AnalyticsFilters,
    AnalyticsReport,
    ArticleViewCreate,
    TrackingDestination,
    TrackingLinkCreate,
    TrackingLinkFilters,
    TrackingLinkResponse,
    TrackingLinkUpdate,
    TrafficOverview,
    TrafficOverviewFilters,
    TrafficSourceCreate,
    TrafficSourceResponse,
    TrafficSourceUpdate,
    UtmLinkCreate,
    UtmLinkResponse,
)
from app.schemas.common import Data, Page, Pagination
from app.services.analytics import create_link, create_utm_link, record_view, report, resolve_link
from app.services.common import audit, transaction
from app.services.traffic_sources import delete_source, save_source, source_overview
from app.utils.pagination import page_response

router = APIRouter(tags=["Traffic analytics"])


@router.post("/admin/tracking-links", status_code=201, response_model=Data[TrackingLinkResponse])
async def create(
    data: TrackingLinkCreate, request: Request, session: Session, actor: Reviewer
) -> Data[TrackingLinkResponse]:
    row = await create_link(session, actor, data, client_ip(request.scope))
    return Data(data=TrackingLinkResponse.model_validate(row))


@router.post("/admin/utm-links", response_model=Data[UtmLinkResponse])
async def create_utm(
    data: UtmLinkCreate, session: Session, actor: Reviewer
) -> Data[UtmLinkResponse]:
    return Data(data=await create_utm_link(session, actor, data))


@router.get("/admin/tracking-links", response_model=Page[TrackingLinkResponse])
async def listing(
    session: Session,
    actor: Reviewer,
    params: Annotated[TrackingLinkFilters, Query()],
) -> Page[TrackingLinkResponse]:
    # Codes act as the search field for the generic listing helper.
    from sqlalchemy import select

    query = select(TrackingLink)
    if params.article_id:
        query = query.where(TrackingLink.article_id == params.article_id)
    if params.search:
        escaped = params.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(TrackingLink.code.ilike(f"%{escaped}%", escape="\\"))
    rows, total = await list_records(
        session,
        TrackingLink,
        params.model_copy(update={"search": None}),
        query=query,
        allowed={"created_at", "code", "source"},
    )
    return page_response([TrackingLinkResponse.model_validate(row) for row in rows], total, params)


@router.patch("/admin/tracking-links/{id}", response_model=Data[TrackingLinkResponse])
async def toggle(
    id: UUID, data: TrackingLinkUpdate, request: Request, session: Session, actor: Reviewer
) -> Data[TrackingLinkResponse]:
    async with transaction(session):
        row = await get_record(session, TrackingLink, id, lock=True)
        row.is_active = data.is_active
        audit(
            session,
            actor,
            "tracking_link.update",
            "tracking_link",
            id,
            client_ip(request.scope),
            {"is_active": data.is_active},
        )
        await session.flush()
    return Data(data=TrackingLinkResponse.model_validate(row))


@router.get(
    "/tracking-links/{code}",
    dependencies=[Depends(public_api_access)],
    response_model=Data[TrackingDestination],
)
async def resolve(
    code: str, request: Request, response: Response, session: Session
) -> Data[TrackingDestination]:
    await request.app.state.limiter.check(
        Limit(f"tracking-resolve:{client_ip(request.scope)}", 6000, 60)
    )
    if len(code) > 80:
        raise APIError(404, "not_found", "Resource not found")
    response.headers["Cache-Control"] = "no-store"
    return Data(data=await resolve_link(session, code))


@router.post("/analytics/article-views", dependencies=[Depends(public_api_access)], status_code=204)
async def ingest(
    data: ArticleViewCreate,
    request: Request,
    session: Session,
    x_analytics_key: Annotated[str | None, Header()] = None,
) -> Response:
    expected = request.app.state.settings.analytics_ingest_secret
    if expected is None:
        raise APIError(503, "analytics_unconfigured", "Analytics is not configured")
    if x_analytics_key is None or not secrets.compare_digest(
        x_analytics_key.encode(), expected.get_secret_value().encode()
    ):
        raise APIError(401, "unauthorized", "Authentication required")
    await request.app.state.limiter.check(
        Limit("analytics-ingest", 6000, 60),
        Limit(f"analytics-session:{data.session_id}", 120, 60),
    )
    await record_view(session, data)
    return Response(status_code=204)


@router.get("/admin/analytics/traffic", response_model=Data[AnalyticsReport])
async def traffic(
    session: Session, actor: Reviewer, params: Annotated[AnalyticsFilters, Query()]
) -> Data[AnalyticsReport]:
    return Data(data=await report(session, params))


@router.get("/admin/traffic-sources", response_model=Page[TrafficSourceResponse])
async def sources(
    session: Session, actor: Reviewer, params: Annotated[Pagination, Query()]
) -> Page[TrafficSourceResponse]:
    rows, total = await list_records(
        session, TrafficSource, params, allowed={"name", "slug", "created_at", "updated_at"}
    )
    return page_response([TrafficSourceResponse.model_validate(row) for row in rows], total, params)


@router.post("/admin/traffic-sources", status_code=201, response_model=Data[TrafficSourceResponse])
async def source_create(
    data: TrafficSourceCreate, request: Request, session: Session, actor: Admin
) -> Data[TrafficSourceResponse]:
    row = await save_source(session, actor, data, client_ip(request.scope))
    return Data(data=TrafficSourceResponse.model_validate(row))


@router.patch("/admin/traffic-sources/{id}", response_model=Data[TrafficSourceResponse])
async def source_update(
    id: UUID, data: TrafficSourceUpdate, request: Request, session: Session, actor: Admin
) -> Data[TrafficSourceResponse]:
    row = await save_source(session, actor, data, client_ip(request.scope), id)
    return Data(data=TrafficSourceResponse.model_validate(row))


@router.delete("/admin/traffic-sources/{id}", status_code=204)
async def source_delete(id: UUID, request: Request, session: Session, actor: Admin) -> Response:
    await delete_source(session, actor, id, client_ip(request.scope))
    return Response(status_code=204)


@router.get("/admin/analytics/sources", response_model=Data[TrafficOverview])
async def overview(
    session: Session, actor: Reviewer, params: Annotated[TrafficOverviewFilters, Query()]
) -> Data[TrafficOverview]:
    return Data(data=await source_overview(session, params))
