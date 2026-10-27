from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.errors import APIError
from app.models import Article
from app.repositories.queries import article_query
from app.schemas.authors import AuthorCreate, AuthorUpdate
from app.schemas.common import ArticleFilters
from app.schemas.content import ArticleCreate, ArticleUpdate
from app.services.articles import apply_relationships


def test_profiles_validate_plain_text_and_required_values():
    profile = AuthorCreate(name=" Jane Doe ", specialization="AI and Technology")
    assert profile.name == "Jane Doe"
    assert profile.specialization == "AI and Technology"
    for payload in ({"name": " "}, {"specialization": None}, {"is_active": None}):
        with pytest.raises(ValidationError):
            AuthorUpdate(**payload)
    with pytest.raises(ValidationError):
        AuthorCreate(name="Jane", specialization=" ")


def test_articles_require_profile_and_protect_creator():
    payload = dict(title="Example", content_html="<p>Example</p>", article_type_id=uuid4())
    with pytest.raises(ValidationError):
        ArticleCreate(**payload)
    profile_id = uuid4()
    assert ArticleCreate(**payload, author_id=profile_id).author_id == profile_id
    assert ArticleUpdate(author_id=profile_id).author_id == profile_id
    with pytest.raises(ValidationError):
        ArticleUpdate(author_id=None)
    with pytest.raises(ValidationError):
        ArticleUpdate(created_by_id=uuid4())


def test_ownership_query_uses_creator_account_not_public_author():
    creator = uuid4()
    query = article_query(ArticleFilters(), public=False, user_id=creator)
    sql = query.compile(dialect=postgresql.dialect())
    assert "articles.created_by_id =" in str(sql)
    assert "articles.author_id =" not in str(sql)
    assert creator in sql.params.values()
    assert next(iter(Article.__table__.c.author_id.foreign_keys)).target_fullname == "authors.id"
    assert next(iter(Article.__table__.c.created_by_id.foreign_keys)).target_fullname == "users.id"


async def test_article_rejects_missing_or_inactive_profile():
    session = AsyncMock()
    session.scalar.return_value = None
    with pytest.raises(APIError) as exc:
        await apply_relationships(session, SimpleNamespace(), {"author_id": uuid4()})
    assert exc.value.code == "invalid_author"
    assert "authors.is_active IS true" in str(session.scalar.call_args.args[0])


async def test_author_dropdown_endpoint_accepts_pagination(client, application, monkeypatch):
    from app.api.dependencies import current_user
    from app.api.v1 import authors

    now = datetime.now(UTC)
    profile = SimpleNamespace(
        id=uuid4(), name="Jane", specialization="AI", is_active=True, created_at=now, updated_at=now
    )
    listing = AsyncMock(return_value=([profile], 1))
    monkeypatch.setattr(authors, "list_records", listing)
    application.dependency_overrides[current_user] = lambda: SimpleNamespace(
        role="author", is_active=True
    )
    try:
        response = await client.get(
            "/api/v1/admin/authors", params={"page_size": 100, "sort": "name"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"][0]["specialization"] == "AI"
        response = await client.post(
            "/api/v1/admin/authors", json={"name": "Jane", "specialization": "AI"}
        )
        assert response.status_code == 403
    finally:
        application.dependency_overrides.clear()


@pytest.mark.integration
async def test_profile_selection_keeps_creator_permissions(db_client, accounts, draft):
    assert draft["author_id"] == accounts["author_id"]
    assert draft["created_by_id"] == str(accounts["author"]["user"].id)
    assert draft["author"]["name"] == "Technology Author"
    assert draft["author"]["specialization"] == "AI and technology"
    response = await db_client.get(
        f"/api/v1/admin/articles/{draft['id']}", headers=accounts["other"]["headers"]
    )
    assert response.status_code == 404
    response = await db_client.delete(
        f"/api/v1/admin/authors/{accounts['author_id']}", headers=accounts["editor"]["headers"]
    )
    assert response.status_code == 409
