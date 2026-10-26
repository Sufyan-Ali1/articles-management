from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.errors import APIError
from app.schemas.content import ArticleSchedule, ArticleUpdate
from app.services import scheduling


def test_schedule_requires_future_timezone():
    for value in ("2030-01-01T09:00:00", "2000-01-01T09:00:00Z"):
        with pytest.raises(ValidationError):
            ArticleSchedule(scheduled_publish_at=value)
    schedule = ArticleSchedule(scheduled_publish_at="2099-01-01T09:00:00+05:00")
    assert schedule.scheduled_publish_at.hour == 4
    assert schedule.scheduled_publish_at.utcoffset() == timedelta(0)
    with pytest.raises(ValidationError):
        ArticleUpdate(scheduled_publish_at="2099-01-01T09:00:00Z")


@pytest.fixture
def context(monkeypatch):
    session = AsyncMock()
    session.add = MagicMock()
    article = SimpleNamespace(
        id=uuid4(),
        status="draft",
        scheduled_publish_at=None,
        published_at=None,
        slug="scheduled-test",
    )

    @asynccontextmanager
    async def transaction(session):
        yield

    monkeypatch.setattr(scheduling, "transaction", transaction)
    monkeypatch.setattr(scheduling, "advisory_lock", AsyncMock())
    monkeypatch.setattr(scheduling, "get_article", AsyncMock(return_value=article))
    monkeypatch.setattr(scheduling, "validate_published", AsyncMock())
    monkeypatch.setattr(scheduling, "audit", MagicMock())
    return session, article


async def test_schedule_reschedule_and_cancel(context):
    session, article = context
    actor = SimpleNamespace(role="editor", is_active=True)
    when = datetime.now(UTC) + timedelta(days=1)
    await scheduling.schedule_article(session, actor, article.id, when, "127.0.0.1")
    assert article.status == "scheduled"
    assert article.scheduled_publish_at == when
    later = when + timedelta(hours=1)
    await scheduling.schedule_article(session, actor, article.id, later, "127.0.0.1")
    assert article.scheduled_publish_at == later
    await scheduling.schedule_article(session, actor, article.id, None, "127.0.0.1")
    assert article.status == "draft"
    assert article.scheduled_publish_at is None


async def test_schedule_permissions_and_transitions(context):
    session, article = context
    when = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(APIError) as exc:
        await scheduling.schedule_article(
            session, SimpleNamespace(role="author", is_active=True), article.id, when, "127.0.0.1"
        )
    assert exc.value.status == 403
    for status in ("published", "archived"):
        article.status = status
        with pytest.raises(APIError) as exc:
            await scheduling.schedule_article(
                session,
                SimpleNamespace(role="admin", is_active=True),
                article.id,
                when,
                "127.0.0.1",
            )
        assert exc.value.status == 409


async def test_worker_rechecks_and_notifies_once(context):
    session, article = context
    article.status = "scheduled"
    article.scheduled_publish_at = datetime.now(UTC) - timedelta(minutes=1)
    session.scalars.return_value = MagicMock()
    session.scalars.return_value.all.return_value = [article.id]
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=session)
    manager.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=manager)
    revalidator = SimpleNamespace(notify=AsyncMock())
    assert await scheduling.publish_due_articles(factory, revalidator) == 1
    assert article.status == "published"
    assert article.scheduled_publish_at is None
    assert article.published_at is not None
    # Simulate another poller's stale selection after publication/cancellation.
    assert await scheduling.publish_due_articles(factory, revalidator) == 0
    revalidator.notify.assert_awaited_once_with("article.publish", article.id, [article.slug])


async def test_worker_keeps_invalid_article_private(context, monkeypatch):
    session, article = context
    article.status = "scheduled"
    article.scheduled_publish_at = datetime.now(UTC) - timedelta(minutes=1)
    session.scalars.return_value = MagicMock()
    session.scalars.return_value.all.return_value = [article.id]
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=session)
    manager.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=manager)
    revalidator = SimpleNamespace(notify=AsyncMock())
    monkeypatch.setattr(
        scheduling,
        "validate_published",
        AsyncMock(side_effect=APIError(422, "publication_invalid", "Inactive author")),
    )
    assert await scheduling.publish_due_articles(factory, revalidator) == 0
    assert article.status == "scheduled"
    revalidator.notify.assert_not_awaited()


@pytest.mark.integration
async def test_scheduled_article_api_lifecycle(db_client, db_app, db_session, accounts, draft):
    from sqlalchemy import update

    from app.models import Article

    url = f"/api/v1/articles/{draft['id']}/schedule"
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    denied = await db_client.post(
        url, headers=accounts["author"]["headers"], json={"scheduled_publish_at": when}
    )
    assert denied.status_code == 403
    response = await db_client.post(
        url, headers=accounts["editor"]["headers"], json={"scheduled_publish_at": when}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "scheduled"
    listing = await db_client.get(
        "/api/v1/admin/articles?status=scheduled", headers=accounts["editor"]["headers"]
    )
    assert listing.status_code == 200
    assert listing.json()["data"][0]["scheduled_publish_at"]
    assert (await db_client.get(f"/api/v1/articles/{draft['slug']}")).status_code == 404
    cancelled = await db_client.delete(url, headers=accounts["editor"]["headers"])
    assert cancelled.json()["data"]["status"] == "draft"
    assert cancelled.json()["data"]["scheduled_publish_at"] is None
    assert (
        await db_client.post(
            url, headers=accounts["editor"]["headers"], json={"scheduled_publish_at": when}
        )
    ).status_code == 200
    await db_session.execute(
        update(Article)
        .where(Article.id == UUID(draft["id"]))
        .values(scheduled_publish_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()
    await scheduling.publish_due_articles(db_app.state.session_factory, db_app.state.revalidator)
    public = await db_client.get(f"/api/v1/articles/{draft['slug']}")
    assert public.status_code == 200
