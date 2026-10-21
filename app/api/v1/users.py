from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.dependencies import Admin, Session
from app.core.middleware import client_ip
from app.models import User
from app.repositories.queries import get_record, list_records
from app.schemas.common import Data, Page, Pagination
from app.schemas.users import UserCreate, UserResponse, UserUpdate
from app.services.users import create_user, update_user
from app.utils.pagination import page_response

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=Page[UserResponse])
async def users(
    session: Session, actor: Admin, params: Annotated[Pagination, Query()]
) -> Page[UserResponse]:
    rows, total = await list_records(
        session, User, params, allowed={"created_at", "updated_at", "name", "email", "role"}
    )
    return page_response([UserResponse.model_validate(row) for row in rows], total, params)


@router.post("", status_code=201, response_model=Data[UserResponse])
async def create(
    data: UserCreate, request: Request, session: Session, actor: Admin
) -> Data[UserResponse]:
    return Data(
        data=UserResponse.model_validate(
            await create_user(session, actor, data, client_ip(request.scope))
        )
    )


@router.get("/{id}", response_model=Data[UserResponse])
async def detail(id: UUID, session: Session, actor: Admin) -> Data[UserResponse]:
    return Data(data=UserResponse.model_validate(await get_record(session, User, id)))


@router.patch("/{id}", response_model=Data[UserResponse])
async def update(
    id: UUID, data: UserUpdate, request: Request, session: Session, actor: Admin
) -> Data[UserResponse]:
    user = await update_user(
        session, actor, id, data, client_ip(request.scope), request.app.state.revalidator
    )
    return Data(data=UserResponse.model_validate(user))


@router.delete("/{id}", status_code=204)
async def deactivate(id: UUID, request: Request, session: Session, actor: Admin) -> Response:
    await update_user(
        session,
        actor,
        id,
        UserUpdate(is_active=False),
        client_ip(request.scope),
        request.app.state.revalidator,
    )
    return Response(status_code=204)
