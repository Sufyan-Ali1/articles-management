from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from app.api.dependencies import Admin, OptionalActor, Session, classification_access
from app.core.errors import not_found
from app.core.middleware import client_ip
from app.models import ArticleType, Category, Tag
from app.repositories.queries import list_records
from app.schemas.common import Data, Page, Pagination
from app.schemas.content import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    ClassificationCreate,
    ClassificationResponse,
    ClassificationUpdate,
)
from app.services.classifications import (
    create_classification,
    delete_classification,
    update_classification,
)
from app.utils.pagination import page_response


class ClassificationFilters(Pagination):
    include_inactive: bool = False


router = APIRouter()
category_router = APIRouter(prefix="/categories", tags=["Categories"])


@category_router.get(
    "", response_model=Page[CategoryResponse], openapi_extra={"security": [{}, {"HTTPBearer": []}]}
)
async def categories(
    session: Session, actor: OptionalActor, params: Annotated[ClassificationFilters, Query()]
) -> Page[CategoryResponse]:
    classification_access(params.include_inactive, actor)
    query = select(Category)
    if not params.include_inactive:
        query = query.where(Category.is_active)
    rows, total = await list_records(session, Category, params, query=query)
    return page_response([CategoryResponse.model_validate(r) for r in rows], total, params)


@category_router.get(
    "/{slug}",
    response_model=Data[CategoryResponse],
    openapi_extra={"security": [{}, {"HTTPBearer": []}]},
)
async def category_detail(
    slug: str, session: Session, actor: OptionalActor, include_inactive: bool = False
) -> Data[CategoryResponse]:
    classification_access(include_inactive, actor)
    query = select(Category).where(Category.slug == slug)
    if not include_inactive:
        query = query.where(Category.is_active)
    row = await session.scalar(query)
    if row is None:
        raise not_found()
    return Data(data=CategoryResponse.model_validate(row))


@category_router.post("", status_code=201, response_model=Data[CategoryResponse])
async def category_create(
    data: CategoryCreate, request: Request, session: Session, actor: Admin
) -> Data[CategoryResponse]:
    row = await create_classification(
        session, Category, actor, data, client_ip(request.scope), request.app.state.revalidator
    )
    return Data(data=CategoryResponse.model_validate(row))


@category_router.patch("/{id}", response_model=Data[CategoryResponse])
async def category_update(
    id: UUID, data: CategoryUpdate, request: Request, session: Session, actor: Admin
) -> Data[CategoryResponse]:
    row = await update_classification(
        session, Category, actor, id, data, client_ip(request.scope), request.app.state.revalidator
    )
    return Data(data=CategoryResponse.model_validate(row))


@category_router.delete("/{id}", status_code=204)
async def category_delete(id: UUID, request: Request, session: Session, actor: Admin) -> Response:
    await delete_classification(
        session, Category, actor, id, client_ip(request.scope), request.app.state.revalidator
    )
    return Response(status_code=204)


def simple_router(model: type[Tag] | type[ArticleType], prefix: str) -> APIRouter:
    result = APIRouter(prefix=prefix, tags=[prefix.strip("/").title()])

    @result.get(
        "",
        response_model=Page[ClassificationResponse],
        name=f"list_{model.__tablename__}",
        openapi_extra={"security": [{}, {"HTTPBearer": []}]},
    )
    async def listing(
        session: Session, actor: OptionalActor, params: Annotated[ClassificationFilters, Query()]
    ) -> Page[ClassificationResponse]:
        classification_access(params.include_inactive, actor)
        query = select(model)
        if not params.include_inactive:
            query = query.where(model.is_active)
        rows, total = await list_records(session, model, params, query=query)
        return page_response(
            [ClassificationResponse.model_validate(r) for r in rows], total, params
        )

    @result.get(
        "/{slug}",
        response_model=Data[ClassificationResponse],
        name=f"get_{model.__tablename__}",
        openapi_extra={"security": [{}, {"HTTPBearer": []}]},
    )
    async def detail(
        slug: str, session: Session, actor: OptionalActor, include_inactive: bool = False
    ) -> Data[ClassificationResponse]:
        classification_access(include_inactive, actor)
        query = select(model).where(model.slug == slug)
        if not include_inactive:
            query = query.where(model.is_active)
        row = await session.scalar(query)
        if row is None:
            raise not_found()
        return Data(data=ClassificationResponse.model_validate(row))

    @result.post(
        "",
        status_code=201,
        response_model=Data[ClassificationResponse],
        name=f"create_{model.__tablename__}",
    )
    async def create(
        data: ClassificationCreate, request: Request, session: Session, actor: Admin
    ) -> Data[ClassificationResponse]:
        row = await create_classification(
            session, model, actor, data, client_ip(request.scope), request.app.state.revalidator
        )
        return Data(data=ClassificationResponse.model_validate(row))

    @result.patch(
        "/{id}", response_model=Data[ClassificationResponse], name=f"update_{model.__tablename__}"
    )
    async def update(
        id: UUID, data: ClassificationUpdate, request: Request, session: Session, actor: Admin
    ) -> Data[ClassificationResponse]:
        row = await update_classification(
            session, model, actor, id, data, client_ip(request.scope), request.app.state.revalidator
        )
        return Data(data=ClassificationResponse.model_validate(row))

    @result.delete("/{id}", status_code=204, name=f"delete_{model.__tablename__}")
    async def delete(id: UUID, request: Request, session: Session, actor: Admin) -> Response:
        await delete_classification(
            session, model, actor, id, client_ip(request.scope), request.app.state.revalidator
        )
        return Response(status_code=204)

    return result


router.include_router(category_router)
router.include_router(simple_router(Tag, "/tags"))
router.include_router(simple_router(ArticleType, "/article-types"))
