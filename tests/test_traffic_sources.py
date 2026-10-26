from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.errors import APIError
from app.schemas.analytics import (
    ArticleViewCreate,
    TrafficOverviewFilters,
    TrafficSourceCreate,
    TrafficSourceUpdate,
)
from app.services import traffic_sources
from app.services.analytics import record_view


def test_source_validation():
    data = TrafficSourceCreate(
        name=" LinkedIn ", slug="linkedin", referrer_domains=["LinkedIn.COM."]
    )
    assert data.name == "LinkedIn" and data.referrer_domains == ["linkedin.com"]
    for domains in (["https://linkedin.com"], ["com"], ["a..com"], ["a.com", "A.COM"]):
        with pytest.raises(ValidationError):
            TrafficSourceCreate(name="LinkedIn", slug="linkedin", referrer_domains=domains)
    with pytest.raises(ValidationError):
        TrafficSourceUpdate(slug="new-key")
    with pytest.raises(ValidationError):
        TrafficSourceUpdate(is_active=None)
    with pytest.raises(ValidationError):
        TrafficOverviewFilters(start=datetime.now())
    with pytest.raises(ValidationError):
        TrafficOverviewFilters(start=datetime.now(UTC), end=datetime.now(UTC) - timedelta(days=1))


async def test_referrer_matches_domain_boundaries():
    session = AsyncMock()
    source = SimpleNamespace(id=uuid4())
    session.scalar.return_value = source
    assert await traffic_sources.match_referrer(session, "www.linkedin.com") == source
    compiled = session.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert ["linkedin.com"] in compiled.params.values()
    assert ["com"] not in compiled.params.values()
    session.scalar.reset_mock()
    assert await traffic_sources.match_referrer(session, None) is None
    session.scalar.assert_not_awaited()


async def test_overlapping_referrer_domains_rejected():
    session = AsyncMock()
    session.scalars.return_value = MagicMock()
    session.scalars.return_value.all.return_value = [
        SimpleNamespace(referrer_domains=["linkedin.com"])
    ]
    with pytest.raises(APIError) as exc:
        await traffic_sources.validate_domains(session, ["www.linkedin.com"])
    assert exc.value.code == "domain_in_use"
    await traffic_sources.validate_domains(session, ["notlinkedin.com"])


async def test_unused_source_can_be_deleted_and_used_source_is_protected(monkeypatch):
    session = AsyncMock()
    session.add = MagicMock()
    source = SimpleNamespace(id=uuid4())
    actor = SimpleNamespace(role="admin", is_active=True)
    monkeypatch.setattr(traffic_sources, "get_record", AsyncMock(return_value=source))
    monkeypatch.setattr(traffic_sources, "audit", MagicMock())
    monkeypatch.setattr(traffic_sources, "advisory_lock", AsyncMock())
    session.scalar.side_effect = [uuid4(), None]
    with pytest.raises(APIError) as exc:
        await traffic_sources.delete_source(session, actor, source.id, "127.0.0.1")
    assert exc.value.code == "source_in_use"
    session.delete.assert_not_awaited()
    session.scalar.side_effect = [None, None]
    await traffic_sources.delete_source(session, actor, source.id, "127.0.0.1")
    session.delete.assert_awaited_once_with(source)


async def test_referrer_event_uses_registered_source(monkeypatch):
    from app.services import analytics

    session = AsyncMock()
    session.scalar.side_effect = [SimpleNamespace(id=uuid4()), uuid4()]
    source = SimpleNamespace(id=uuid4(), slug="linkedin")
    monkeypatch.setattr(analytics, "match_referrer", AsyncMock(return_value=source))
    await record_view(
        session,
        ArticleViewCreate(
            event_id=uuid4(),
            session_id=uuid4(),
            article_slug="example",
            referrer_domain="www.linkedin.com",
        ),
    )
    values = session.scalar.call_args_list[1].args[0].compile(dialect=postgresql.dialect()).params
    assert values["source_id"] == source.id and values["source"] == "linkedin"


@pytest.mark.integration
async def test_sources_counts_include_zero_and_are_article_scoped(
    db_client, db_session, db_app, accounts, draft
):
    from pydantic import SecretStr

    admin = accounts["admin"]["headers"]
    editor = accounts["editor"]["headers"]
    db_app.state.settings.analytics_ingest_secret = SecretStr(
        "test-only-analytics-ingest-key-over-32-characters"
    )
    source_ids = []
    for name in ("LinkedIn", "Instagram"):
        response = await db_client.post(
            "/api/v1/admin/traffic-sources",
            headers=admin,
            json={"name": name, "slug": name.lower(), "referrer_domains": [name.lower() + ".com"]},
        )
        assert response.status_code == 201, response.text
        source_ids.append(response.json()["data"]["id"])
    assert (
        await db_client.post(
            "/api/v1/admin/traffic-sources", headers=editor, json={"name": "Other", "slug": "other"}
        )
    ).status_code == 403
    await db_client.post(f"/api/v1/articles/{draft['id']}/publish", headers=editor)
    response = await db_client.get(
        "/api/v1/admin/analytics/sources", headers=editor, params={"article_id": draft["id"]}
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]["sources"]) == 2
    assert all(row["views"] == 0 for row in response.json()["data"]["sources"])
    body = {
        "event_id": str(uuid4()),
        "session_id": str(uuid4()),
        "article_slug": draft["slug"],
        "referrer_domain": "www.linkedin.com",
    }
    assert (
        await db_client.post(
            "/api/v1/analytics/article-views",
            json=body,
            headers={"X-Analytics-Key": "test-only-analytics-ingest-key-over-32-characters"},
        )
    ).status_code == 204
    response = await db_client.get(
        "/api/v1/admin/analytics/sources", headers=editor, params={"article_id": draft["id"]}
    )
    data = response.json()["data"]
    assert data["views"] == data["sessions"] == data["lifetime_views"] == 1
    assert next(row for row in data["sources"] if row["slug"] == "linkedin")["views"] == 1
    assert next(row for row in data["sources"] if row["slug"] == "instagram")["views"] == 0
    assert (
        await db_client.delete(f"/api/v1/admin/traffic-sources/{source_ids[0]}", headers=admin)
    ).status_code == 409
    assert (
        await db_client.patch(
            f"/api/v1/admin/traffic-sources/{source_ids[0]}",
            headers=admin,
            json={"is_active": False},
        )
    ).status_code == 200
    assert (
        await db_client.delete(f"/api/v1/admin/traffic-sources/{source_ids[1]}", headers=admin)
    ).status_code == 204
    response = await db_client.get(
        "/api/v1/admin/analytics/sources", headers=editor, params={"article_id": str(uuid4())}
    )
    assert response.status_code == 404
    # Empty date ranges retain the configured card and historical lifetime counter.
    response = await db_client.get(
        "/api/v1/admin/analytics/sources",
        headers=editor,
        params={"start": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    )
    assert response.json()["data"]["views"] == 0
    assert response.json()["data"]["lifetime_views"] == 1


async def test_overview_keeps_zero_sources_and_compiles_one_snapshot_query():
    session = AsyncMock()
    now = datetime.now(UTC)
    source = SimpleNamespace(
        id=uuid4(),
        name="LinkedIn",
        slug="linkedin",
        referrer_domains=["linkedin.com"],
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    row = SimpleNamespace(
        TrafficSource=source,
        source_views=None,
        source_sessions=None,
        views=2,
        sessions=1,
        lifetime_views=5,
        recorded_views=2,
        unassigned_views=2,
        unassigned_sessions=1,
    )
    session.execute.return_value = MagicMock()
    session.execute.return_value.all.return_value = [row]
    data = await traffic_sources.source_overview(session, TrafficOverviewFilters())
    assert data.sources[0].views == 0
    assert data.legacy_views == 3 and data.unassigned_views == 2
    compiled = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "LEFT OUTER JOIN traffic_sources" in str(compiled)
    assert "COUNT" in str(compiled).upper()


async def test_article_overview_filters_both_event_and_lifetime_counts(monkeypatch):
    identity = uuid4()
    session = AsyncMock()
    monkeypatch.setattr(traffic_sources, "get_record", AsyncMock())
    row = SimpleNamespace(
        TrafficSource=None,
        source_views=None,
        source_sessions=None,
        views=0,
        sessions=0,
        lifetime_views=0,
        recorded_views=0,
        unassigned_views=0,
        unassigned_sessions=0,
    )
    session.execute.return_value = MagicMock()
    session.execute.return_value.all.return_value = [row]
    result = await traffic_sources.source_overview(
        session, TrafficOverviewFilters(article_id=identity)
    )
    assert result.sources == []
    compiled = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "article_view_events.article_id =" in str(compiled)
    assert "articles.id =" in str(compiled)
    assert sum(value == identity for value in compiled.params.values()) == 2
