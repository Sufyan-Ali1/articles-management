from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from app.api.dependencies import Actor, Reviewer, Session
from app.core.errors import APIError
from app.core.middleware import client_ip
from app.models import Article, Author
from app.repositories.queries import get_record, list_records
from app.schemas.authors import AuthorCreate, AuthorFilters, AuthorResponse, AuthorUpdate
from app.schemas.common import Data, Page
from app.services.classifications import CLASSIFICATION_LOCK
from app.services.common import advisory_lock, audit, transaction
from app.utils.pagination import page_response

router = APIRouter(prefix="/admin/authors", tags=["Authors"])


@router.get("", response_model=Page[AuthorResponse])
async def listing(
    session: Session, actor: Actor, params: Annotated[AuthorFilters, Query()]
) -> Page[AuthorResponse]:
    query = select(Author)
    if not params.include_inactive:
        query = query.where(Author.is_active.is_(True))
    rows, total = await list_records(
        session, Author, params, query=query, allowed={"name", "created_at", "updated_at"}
    )
    return page_response([AuthorResponse.model_validate(row) for row in rows], total, params)


@router.post("", status_code=201, response_model=Data[AuthorResponse])
async def create(
    data: AuthorCreate, request: Request, session: Session, actor: Reviewer
) -> Data[AuthorResponse]:
    async with transaction(session):
        row = Author(**data.model_dump())
        session.add(row)
        await session.flush()
        audit(session, actor, "author.create", "author", row.id, client_ip(request.scope))
        await session.refresh(row)
    return Data(data=AuthorResponse.model_validate(row))


@router.patch("/{id}", response_model=Data[AuthorResponse])
async def update(
    id: UUID, data: AuthorUpdate, request: Request, session: Session, actor: Reviewer
) -> Data[AuthorResponse]:
    async with transaction(session):
        await advisory_lock(session, CLASSIFICATION_LOCK)
        row = await get_record(session, Author, id, lock=True)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        await session.flush()
        audit(session, actor, "author.update", "author", row.id, client_ip(request.scope))
    await request.app.state.revalidator.notify("author.update", row.id, [])
    return Data(data=AuthorResponse.model_validate(row))


@router.delete("/{id}", status_code=204)
async def delete(id: UUID, request: Request, session: Session, actor: Reviewer) -> Response:
    async with transaction(session):
        await advisory_lock(session, CLASSIFICATION_LOCK)
        row = await get_record(session, Author, id, lock=True)
        if await session.scalar(select(Article.id).where(Article.author_id == id).limit(1)):
            raise APIError(409, "author_in_use", "This author has articles; deactivate instead")
        audit(session, actor, "author.delete", "author", id, client_ip(request.scope))
        await session.delete(row)
        await session.flush()
    return Response(status_code=204)
