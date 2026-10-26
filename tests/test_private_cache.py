import httpx
import pytest
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from app.core.config import Settings
from app.core.limits import RateLimiter
from app.core.middleware import RequestProtection


@pytest.mark.parametrize(
    ("method", "path", "headers", "expected"),
    [
        (
            "GET",
            "/api/v1/categories?include_inactive=true",
            {"Authorization": "Bearer test-only"},
            "no-store",
        ),
        ("GET", "/api/v1/categories", {"X-API-Key": "service-key"}, "no-store"),
        ("GET", "/api/v1/tags", {"Cookie": "test-session=test-only"}, "no-store"),
        ("GET", "/api/v1/admin/articles", {}, "no-store"),
        ("POST", "/api/v1/articles", {}, "no-store"),
        ("GET", "/api/v1/categories", {}, "public, max-age=600"),
    ],
)
async def test_private_cache_policy_overrides_route_headers(
    settings: Settings, method: str, path: str, headers: dict[str, str], expected: str
) -> None:
    async def endpoint(scope: Scope, receive: Receive, send: Send) -> None:
        await PlainTextResponse("ok", headers={"Cache-Control": "public, max-age=600"})(
            scope, receive, send
        )

    app = RequestProtection(endpoint, settings, RateLimiter())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, headers=headers)
    assert response.status_code == 200
    assert response.headers.get_list("cache-control") == [expected]
