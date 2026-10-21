from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.dependencies import Admin, Session
from app.models import AdminLog
from app.repositories.queries import get_record, list_records
from app.schemas.common import Data, Page, Pagination
from app.schemas.logs import LogResponse
from app.utils.pagination import page_response

router = APIRouter(prefix="/admin-logs", tags=["Audit logs"])


class LogFilters(Pagination):
    user_id: UUID | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None


@router.get("", response_model=Page[LogResponse])
async def listing(
    session: Session, actor: Admin, params: Annotated[LogFilters, Query()]
) -> Page[LogResponse]:
    query = select(AdminLog)
    for field in ("user_id", "entity_type", "entity_id"):
        if (value := getattr(params, field)) is not None:
            query = query.where(getattr(AdminLog, field) == value)
    rows, total = await list_records(
        session, AdminLog, params, query=query, allowed={"created_at", "action", "entity_type"}
    )
    return page_response([LogResponse.model_validate(row) for row in rows], total, params)


@router.get("/{id}", response_model=Data[LogResponse])
async def detail(id: UUID, session: Session, actor: Admin) -> Data[LogResponse]:
    return Data(data=LogResponse.model_validate(await get_record(session, AdminLog, id)))
