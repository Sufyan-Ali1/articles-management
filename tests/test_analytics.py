import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.core.errors import APIError
from app.models import Article, ArticleViewEvent
from app.schemas.analytics import AnalyticsFilters, ArticleViewCreate, TrackingLinkCreate
from app.services.analytics import record_view, report

SECRET = "test-only-analytics-ingest-key-over-32-characters"


def test_analytics_inputs():
    link = TrackingLinkCreate(article_id=uuid4(), code="linkedin-comment-01", source=" LinkedIn ")
    assert link.source == "linkedin"
    with pytest.raises(ValidationError):
        TrackingLinkCreate(article_id=uuid4(), code="https://evil.test", source="linkedin")
    with pytest.raises(ValidationError):
        AnalyticsFilters(start=datetime.now(), end=datetime.now())
    with pytest.raises(ValidationError):
        AnalyticsFilters(start=datetime.now(UTC) - timedelta(days=400))
    with pytest.raises(ValidationError):
        ArticleViewCreate(
            event_id=uuid4(),
            session_id=uuid4(),
            article_slug="example",
            referrer_domain="https://linkedin.com/private",
        )


async def test_ingest_requires_server_secret(client, application, monkeypatch):
    from app.api.v1 import analytics

    save = AsyncMock()
    monkeypatch.setattr(analytics, "record_view", save)
    data = {"event_id": str(uuid4()), "session_id": str(uuid4()), "article_slug": "example"}
    assert (await client.post("/api/v1/analytics/article-views", json=data)).status_code == 503
    application.state.settings.analytics_ingest_secret = SecretStr(SECRET)
    assert (await client.post("/api/v1/analytics/article-views", json=data)).status_code == 401
    assert (
        await client.post(
            "/api/v1/analytics/article-views", json=data, headers={"X-Analytics-Key": "wrong"}
        )
    ).status_code == 401
    response = await client.post(
        "/api/v1/analytics/article-views", json=data, headers={"X-Analytics-Key": SECRET}
    )
    assert response.status_code == 204
    save.assert_awaited_once()
    for path in ("/admin/tracking-links", "/admin/analytics/traffic"):
        assert (await client.get("/api/v1" + path)).status_code == 401


async def test_duplicate_event_does_not_increment_count():
    article = SimpleNamespace(id=uuid4())
    session = AsyncMock()
    session.scalar.side_effect = [article, None]
    data = ArticleViewCreate(event_id=uuid4(), session_id=uuid4(), article_slug="example")
    await record_view(session, data)
    session.execute.assert_not_awaited()
    session.commit.assert_awaited_once()


async def test_new_view_increments_count_atomically_and_uses_link_metadata():
    article = SimpleNamespace(id=uuid4())
    link = SimpleNamespace(
        source_id=uuid4(),
        id=uuid4(),
        source="linkedin",
        medium="social",
        campaign="launch",
        content="comment-01",
    )
    session = AsyncMock()
    session.scalar.side_effect = [article, uuid4()]
    session.get.return_value = link
    data = ArticleViewCreate(
        event_id=uuid4(), session_id=uuid4(), article_slug="example", tracking_link_id=link.id
    )
    await record_view(session, data)
    stmt = session.scalar.call_args_list[1].args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert compiled.params["source"] == "linkedin"
    assert compiled.params["campaign"] == "launch"
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


async def test_unpublished_views_rejected():
    session = AsyncMock()
    session.scalar.return_value = None
    with pytest.raises(APIError) as exc:
        await record_view(
            session, ArticleViewCreate(event_id=uuid4(), session_id=uuid4(), article_slug="example")
        )
    assert exc.value.status == 404
    session.rollback.assert_awaited_once()


@pytest.mark.integration
async def test_tracking_link_and_report_lifecycle(db_client, db_session, db_app, accounts, draft):
    db_app.state.settings.analytics_ingest_secret = SecretStr(SECRET)
    editor = accounts["editor"]["headers"]
    created_source = await db_client.post(
        "/api/v1/admin/traffic-sources",
        headers=accounts["admin"]["headers"],
        json={"name": "LinkedIn", "slug": "linkedin", "referrer_domains": ["linkedin.com"]},
    )
    assert created_source.status_code == 201, created_source.text
    data = {
        "article_id": draft["id"],
        "code": "linkedin-comment-01",
        "source": "linkedin",
        "campaign": "launch",
        "content": "comment-01",
    }
    assert (
        await db_client.post("/api/v1/admin/tracking-links", headers=editor, json=data)
    ).status_code == 409
    assert (
        await db_client.post(f"/api/v1/articles/{draft['id']}/publish", headers=editor)
    ).status_code == 200
    assert (
        await db_client.post(
            "/api/v1/admin/tracking-links", headers=accounts["author"]["headers"], json=data
        )
    ).status_code == 403
    response = await db_client.post("/api/v1/admin/tracking-links", headers=editor, json=data)
    assert response.status_code == 201, response.text
    link = response.json()["data"]
    assert (
        await db_client.post("/api/v1/admin/tracking-links", headers=editor, json=data)
    ).status_code == 409
    resolved = await db_client.get(f"/api/v1/tracking-links/{link['code']}")
    assert resolved.status_code == 200
    assert resolved.json()["data"]["article_slug"] == draft["slug"]
    event = {
        "event_id": str(uuid4()),
        "session_id": str(uuid4()),
        "article_slug": draft["slug"],
        "tracking_link_id": link["id"],
    }
    responses = await asyncio.gather(
        *(
            db_client.post(
                "/api/v1/analytics/article-views", json=event, headers={"X-Analytics-Key": SECRET}
            )
            for _ in range(3)
        )
    )
    assert all(response.status_code == 204 for response in responses)
    assert await db_session.scalar(select(func.count()).select_from(ArticleViewEvent)) == 1
    assert (
        await db_session.scalar(select(Article.view_count).where(Article.id == UUID(draft["id"])))
        == 1
    )
    for grouping in ("source", "article", "campaign", "link", "day"):
        response = await db_client.get(
            f"/api/v1/admin/analytics/traffic?group_by={grouping}", headers=editor
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["views"] == 1
        assert response.json()["data"]["sessions"] == 1
    empty_page = await report(db_session, AnalyticsFilters(page=100))
    assert empty_page.views == 1 and empty_page.groups == []
    assert (
        await db_client.patch(
            f"/api/v1/admin/tracking-links/{link['id']}", headers=editor, json={"is_active": False}
        )
    ).status_code == 200
    assert (await db_client.get(f"/api/v1/tracking-links/{link['code']}")).status_code == 404


def test_empty_analytics_secret_disables_ingestion(settings):
    config = type(settings)(**{**settings.model_dump(), "analytics_ingest_secret": ""})
    assert config.analytics_ingest_secret is None
