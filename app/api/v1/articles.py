from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.dependencies import Actor, Admin, Reviewer, Session
from app.core.errors import not_found
from app.core.middleware import client_ip
from app.models import Article
from app.repositories.queries import article_query, get_article, list_records
from app.schemas.common import ArticleFilters, Data, Page, PublicArticleFilters
from app.schemas.content import (
    AdminArticleResponse,
    AdminArticleSummary,
    ArticleCreate,
    ArticleResponse,
    ArticleSummary,
    ArticleUpdate,
)
from app.services.articles import (
    create_article,
    delete_article,
    public_detail,
    publish_article,
    update_article,
)
from app.utils.pagination import page_response

router = APIRouter(tags=["Articles"])
SORTS = {"title", "created_at", "updated_at", "published_at", "view_count"}


@router.get("/articles", response_model=Page[ArticleSummary])
async def public_articles(
    session: Session, params: Annotated[PublicArticleFilters, Query()]
) -> Page[ArticleSummary]:
    rows, total = await list_records(
        session, Article, params, query=article_query(params, public=True), allowed=SORTS
    )
    return page_response([ArticleSummary.model_validate(r) for r in rows], total, params)


@router.get("/articles/{slug}", response_model=Data[ArticleResponse])
async def article_detail(slug: str, session: Session) -> Data[ArticleResponse]:
    return Data(data=ArticleResponse.model_validate(await public_detail(session, slug)))


@router.get("/admin/articles", response_model=Page[AdminArticleSummary])
async def admin_articles(
    session: Session, actor: Actor, params: Annotated[ArticleFilters, Query()]
) -> Page[AdminArticleSummary]:
    query = article_query(
        params, public=False, user_id=actor.id if actor.role == "author" else None
    )
    rows, total = await list_records(session, Article, params, query=query, allowed=SORTS)
    return page_response([AdminArticleSummary.model_validate(r) for r in rows], total, params)


@router.get("/admin/articles/{id}", response_model=Data[AdminArticleResponse])
async def admin_detail(id: UUID, session: Session, actor: Actor) -> Data[AdminArticleResponse]:
    row = await get_article(session, id)
    if actor.role == "author" and row.author_id != actor.id:
        raise not_found()
    return Data(data=AdminArticleResponse.model_validate(row))


@router.post("/articles", status_code=201, response_model=Data[AdminArticleResponse])
async def create(
    data: ArticleCreate, request: Request, session: Session, actor: Actor
) -> Data[AdminArticleResponse]:
    row = await create_article(session, actor, data, client_ip(request.scope))
    return Data(data=AdminArticleResponse.model_validate(row))


@router.patch("/articles/{id}", response_model=Data[AdminArticleResponse])
async def update(
    id: UUID, data: ArticleUpdate, request: Request, session: Session, actor: Actor
) -> Data[AdminArticleResponse]:
    row = await update_article(
        session, actor, id, data, client_ip(request.scope), request.app.state.revalidator
    )
    return Data(data=AdminArticleResponse.model_validate(row))


@router.delete("/articles/{id}", status_code=204)
async def delete(id: UUID, request: Request, session: Session, actor: Admin) -> Response:
    await delete_article(
        session, actor, id, client_ip(request.scope), request.app.state.revalidator
    )
    return Response(status_code=204)


@router.post("/articles/{id}/publish", response_model=Data[AdminArticleResponse])
async def publish(
    id: UUID, request: Request, session: Session, actor: Reviewer
) -> Data[AdminArticleResponse]:
    row = await publish_article(
        session, actor, id, True, client_ip(request.scope), request.app.state.revalidator
    )
    return Data(data=AdminArticleResponse.model_validate(row))


@router.post("/articles/{id}/unpublish", response_model=Data[AdminArticleResponse])
async def unpublish(
    id: UUID, request: Request, session: Session, actor: Reviewer
) -> Data[AdminArticleResponse]:
    row = await publish_article(
        session, actor, id, False, client_ip(request.scope), request.app.state.revalidator
    )
    return Data(data=AdminArticleResponse.model_validate(row))
