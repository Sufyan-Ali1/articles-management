import httpx
import pytest
from sqlalchemy import select

from app.models import RefreshSession
from tests.conftest import PASSWORD


@pytest.mark.integration
async def test_rotation_logout_and_revocation(db_client, accounts, db_session):
    headers = {"X-CSRF-Protection": "1"}
    response = await db_client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"email": "admin@example.com", "password": PASSWORD},
    )
    assert response.status_code == 200
    access = response.json()["data"]["access_token"]
    original = db_client.cookies.get("blog_refresh")
    assert original and "HttpOnly" in response.headers["set-cookie"]
    record = await db_session.scalar(select(RefreshSession))
    assert record.token_hash != original
    response = await db_client.post("/api/v1/auth/refresh", headers=headers)
    assert response.status_code == 200
    rotated = db_client.cookies.get("blog_refresh")
    assert rotated != original
    response = await db_client.post(
        "/api/v1/auth/refresh", headers={**headers, "Cookie": f"blog_refresh={original}"}
    )
    assert response.status_code == 401
    response = await db_client.post("/api/v1/auth/refresh", headers=headers)
    assert response.status_code == 200
    response = await db_client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204
    assert not db_client.cookies.get("blog_refresh")
    assert (
        await db_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    ).status_code == 401
    assert (await db_client.post("/api/v1/auth/refresh", headers=headers)).status_code == 401


async def test_refresh_csrf(client: httpx.AsyncClient):
    assert (await client.post("/api/v1/auth/refresh")).status_code == 403
    assert (
        await client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Protection": "1", "Origin": "https://untrusted.example"},
        )
    ).status_code == 403


@pytest.mark.integration
@pytest.mark.parametrize("change", ["inactive", "password", "expired"])
async def test_session_invalidation(db_client, accounts, db_session, change):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.models import User

    headers = {"X-CSRF-Protection": "1"}
    response = await db_client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"email": "admin@example.com", "password": PASSWORD},
    )
    access = response.json()["data"]["access_token"]
    if change == "expired":
        await db_session.execute(
            update(RefreshSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    else:
        values = (
            {"is_active": False}
            if change == "inactive"
            else {"password_hash": "changed-password-hash"}
        )
        await db_session.execute(
            update(User).where(User.id == accounts["admin"]["user"].id).values(**values)
        )
    await db_session.commit()
    assert (await db_client.post("/api/v1/auth/refresh", headers=headers)).status_code == 401
    assert (
        await db_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    ).status_code == 401
