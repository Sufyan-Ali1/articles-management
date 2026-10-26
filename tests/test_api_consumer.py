from unittest.mock import AsyncMock

import httpx
import pytest

from app.api.dependencies import optional_user
from app.core.api_consumer import valid_api_consumer
from tests.conftest import API_HEADERS


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/articles", None),
        ("GET", "/api/v1/articles/example", None),
        ("GET", "/api/v1/categories", None),
        ("GET", "/api/v1/tags", None),
        ("GET", "/api/v1/article-types", None),
        ("GET", "/api/v1/tracking-links/example", None),
        ("POST", "/api/v1/subscriptions", {"email": "reader@example.com"}),
        (
            "POST",
            "/api/v1/contact-messages",
            {"email": "reader@example.com", "reason": "general", "message": "Hello"},
        ),
        ("POST", "/api/v1/article-requests", {"topic": "A useful topic"}),
        (
            "POST",
            "/api/v1/analytics/article-views",
            {
                "event_id": "00000000-0000-4000-8000-000000000001",
                "session_id": "00000000-0000-4000-8000-000000000002",
                "article_slug": "example",
            },
        ),
    ],
)
async def test_public_routes_require_both_credentials(application, method, path, body):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        for headers in (
            {},
            {"X-API-User": API_HEADERS["X-API-User"]},
            {**API_HEADERS, "X-API-Key": "wrong"},
        ):
            response = await client.request(method, path, json=body, headers=headers)
            assert response.status_code == 401, (path, response.text)
            assert API_HEADERS["X-API-Key"] not in response.text


async def test_key_grants_no_staff_access(client):
    assert (await client.get("/api/v1/admin/articles")).status_code == 401
    assert (await client.get("/api/v1/users")).status_code == 401
    # Login remains independent of service credentials.
    client.headers.clear()
    assert (await client.post("/api/v1/auth/login", json={})).status_code == 422
    assert (await client.get("/health")).status_code == 200


async def test_missing_configuration_fails_closed(client, application):
    application.state.settings.api_user = None
    application.state.settings.api_key = None
    assert (await client.get("/api/v1/articles")).status_code == 503
    assert (await client.get("/api/v1/admin/articles")).status_code == 401


async def test_validated_staff_taxonomy_access_does_not_need_service_keys(client, application):
    from types import SimpleNamespace

    actor = SimpleNamespace(id="staff", role="admin", is_active=True)
    application.dependency_overrides[optional_user] = lambda: actor
    client.headers.clear()
    # Use a missing slug to reach the protected handler with a controlled result.
    fake = AsyncMock()
    fake.scalar.return_value = None
    from app.db.session import get_session

    async def session():
        yield fake

    application.dependency_overrides[get_session] = session
    response = await client.get("/api/v1/categories/missing")
    assert response.status_code == 404
    application.dependency_overrides.clear()


async def test_forwarded_ip_requires_consumer_credentials(client, application, monkeypatch):
    from app.api.v1 import requests

    seen = []

    async def save(session, data, ip, guard):
        seen.append(ip)

    monkeypatch.setattr(requests, "submit_request", save)
    response = await client.post(
        "/api/v1/article-requests", json={"topic": "Hello"}, headers={"X-Visitor-IP": "203.0.113.9"}
    )
    assert response.status_code == 202
    assert seen == ["203.0.113.9"]
    client.headers.clear()
    response = await client.post(
        "/api/v1/article-requests",
        json={"topic": "Hello"},
        headers={"X-Visitor-IP": "203.0.113.10"},
    )
    assert response.status_code == 401
    assert seen == ["203.0.113.9"]


def test_constant_time_match_rejects_partial_credentials(settings):
    assert valid_api_consumer(settings, *API_HEADERS.values())
    assert not valid_api_consumer(settings, "wrong", API_HEADERS["X-API-Key"])
