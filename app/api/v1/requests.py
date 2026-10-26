from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select

from app.api.dependencies import Admin, Reviewer, Session, public_api_access
from app.core.middleware import client_ip
from app.models import ArticleRequest
from app.repositories.queries import get_record, list_records
from app.schemas.common import Data, Page, Pagination, RequestStatus
from app.schemas.requests import RequestCreate, RequestResponse, RequestUpdate, SubmissionResponse
from app.services.requests import delete_request, review_request, submit_request
from app.utils.pagination import page_response

router = APIRouter(tags=["Article requests"])


class RequestFilters(Pagination):
    status: RequestStatus | None = None


@router.post(
    "/article-requests",
    dependencies=[Depends(public_api_access)],
    status_code=202,
    response_model=Data[SubmissionResponse],
)
async def submit(
    data: RequestCreate, request: Request, session: Session
) -> Data[SubmissionResponse]:
    await submit_request(
        session, data, client_ip(request.scope), request.app.state.submission_guard
    )
    return Data(data=SubmissionResponse())


@router.get("/admin/article-requests", response_model=Page[RequestResponse])
async def listing(
    session: Session, actor: Reviewer, params: Annotated[RequestFilters, Query()]
) -> Page[RequestResponse]:
    query = select(ArticleRequest)
    if params.status:
        query = query.where(ArticleRequest.status == params.status)
    rows, total = await list_records(
        session,
        ArticleRequest,
        params,
        query=query,
        allowed={"created_at", "updated_at", "topic", "status"},
    )
    return page_response([RequestResponse.model_validate(row) for row in rows], total, params)


@router.get("/admin/article-requests/{id}", response_model=Data[RequestResponse])
async def detail(id: UUID, session: Session, actor: Reviewer) -> Data[RequestResponse]:
    return Data(data=RequestResponse.model_validate(await get_record(session, ArticleRequest, id)))


@router.patch("/admin/article-requests/{id}", response_model=Data[RequestResponse])
async def review(
    id: UUID, data: RequestUpdate, request: Request, session: Session, actor: Reviewer
) -> Data[RequestResponse]:
    row = await review_request(session, actor, id, data, client_ip(request.scope))
    return Data(data=RequestResponse.model_validate(row))


@router.delete("/admin/article-requests/{id}", status_code=204)
async def delete(id: UUID, request: Request, session: Session, actor: Admin) -> Response:
    await delete_request(session, actor, id, client_ip(request.scope))
    return Response(status_code=204)
