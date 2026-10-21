import asyncio

import httpx
from fastapi import FastAPI


async def test_health_readiness(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"data": {"status": "ok"}}
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "not_ready"
    assert "postgres" not in response.text


async def test_openapi(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert len(document["paths"]) >= 25
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    public = document["paths"]["/api/v1/articles"]["get"]
    assert "status" not in [p["name"] for p in public["parameters"]]
    assert "security" not in document["paths"]["/api/v1/article-requests"]["post"]
    assert document["paths"]["/api/v1/admin/article-requests"]["get"]["security"]


async def test_errors_and_body_limit(client: httpx.AsyncClient, application: FastAPI) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "bad", "password": "private-do-not-echo"}
    )
    assert response.status_code == 422
    assert "private-do-not-echo" not in response.text
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]
    application.state.settings.max_body_bytes = 1024
    response = await client.post("/api/v1/article-requests", content="x" * 1025)
    assert response.status_code == 413
    assert (await client.get("/not-found")).status_code == 404


async def test_unauthenticated_permissions(client: httpx.AsyncClient) -> None:
    for path in ("/users", "/admin/articles", "/admin/article-requests", "/admin-logs"):
        assert (await client.get("/api/v1" + path)).status_code == 401


async def test_honeypot_and_submission_limits_without_db(client: httpx.AsyncClient) -> None:
    responses = [
        await client.post(
            "/api/v1/article-requests",
            json={"topic": "A suggestion", "website": "https://spam.example"},
        )
        for _ in range(6)
    ]
    assert all(r.status_code == 202 for r in responses[:5])
    assert responses[-1].status_code == 429
    assert int(responses[-1].headers["retry-after"]) > 0
    assert responses[0].json() == {"data": {"message": "Thank you for your suggestion."}}


async def test_concurrent_health(client: httpx.AsyncClient) -> None:
    responses = await asyncio.gather(*(client.get("/health") for _ in range(25)))
    assert all(r.status_code == 200 for r in responses)


async def test_login_rate_limit_includes_invalid_bodies(
    client: httpx.AsyncClient, application: FastAPI
) -> None:
    application.state.settings.login_ip_per_minute = 2
    assert (await client.post("/api/v1/auth/login", json={})).status_code == 422
    assert (await client.post("/api/v1/auth/login", json={})).status_code == 422
    assert (await client.post("/api/v1/auth/login", json={})).status_code == 429


async def test_inactive_classifications_require_admin(client: httpx.AsyncClient) -> None:
    for path in ("categories", "tags", "article-types"):
        assert (await client.get(f"/api/v1/{path}?include_inactive=true")).status_code == 401
        assert (
            await client.get(f"/api/v1/{path}/inactive?include_inactive=true")
        ).status_code == 401
