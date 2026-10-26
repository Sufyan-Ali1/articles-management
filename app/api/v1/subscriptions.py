from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.dependencies import Admin, Session, public_api_access
from app.models import Subscriber
from app.repositories.queries import list_records
from app.schemas.common import Data, Page, Pagination
from app.schemas.subscriptions import (
    SubscriptionAccepted,
    SubscriptionCreate,
    SubscriptionResponse,
)
from app.services.subscriptions import subscribe
from app.utils.pagination import page_response

router = APIRouter(tags=["Subscriptions"])


@router.post(
    "/subscriptions",
    dependencies=[Depends(public_api_access)],
    status_code=202,
    response_model=Data[SubscriptionAccepted],
)
async def create(data: SubscriptionCreate, session: Session) -> Data[SubscriptionAccepted]:
    await subscribe(session, data)
    return Data(data=SubscriptionAccepted())


@router.get("/admin/subscriptions", response_model=Page[SubscriptionResponse])
async def listing(
    session: Session, actor: Admin, params: Annotated[Pagination, Query()]
) -> Page[SubscriptionResponse]:
    query = select(Subscriber)
    if params.search:
        escaped = params.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Subscriber.email.ilike(f"%{escaped}%", escape="\\"))
    rows, total = await list_records(
        session,
        Subscriber,
        params.model_copy(update={"search": None}),
        query=query,
        allowed={"created_at", "email"},
    )
    return page_response([SubscriptionResponse.model_validate(row) for row in rows], total, params)
