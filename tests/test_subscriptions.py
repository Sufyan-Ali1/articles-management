from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.models import Subscriber
from app.schemas.subscriptions import SubscriptionCreate


def test_subscription_email_validation():
    assert SubscriptionCreate(email="  Reader@Example.COM  ").email == "reader@example.com"
    for data in (
        {},
        {"email": "invalid"},
        {"email": None},
        {"email": "x@example.com", "name": "extra"},
    ):
        with pytest.raises(ValidationError):
            SubscriptionCreate(**data)


async def test_subscription_public_contract(client, monkeypatch):
    from app.api.v1 import subscriptions

    save = AsyncMock()
    monkeypatch.setattr(subscriptions, "subscribe", save)
    for email in ("Reader@Example.com", "reader@example.com"):
        response = await client.post("/api/v1/subscriptions", json={"email": email})
        assert response.status_code == 202
        assert response.json() == {"data": {"message": "Thank you for subscribing."}}
        assert response.headers["cache-control"] == "no-store"
    assert save.await_count == 2
    assert save.call_args.args[1].email == "reader@example.com"
    assert (await client.get("/api/v1/admin/subscriptions")).status_code == 401


async def test_subscription_rate_limit_and_invalid_input(client):
    for _ in range(5):
        response = await client.post(
            "/api/v1/subscriptions", json={"email": "private-invalid-email"}
        )
        assert response.status_code == 422
        assert "private-invalid-email" not in response.text
    response = await client.post("/api/v1/subscriptions", json={"email": "reader@example.com"})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


@pytest.mark.integration
async def test_subscription_storage_and_admin_access(db_client, db_session, accounts):
    import asyncio

    responses = await asyncio.gather(
        *(
            db_client.post("/api/v1/subscriptions", json={"email": email})
            for email in ("Reader@Example.com", "reader@example.com")
        )
    )
    assert all(response.status_code == 202 for response in responses)
    assert await db_session.scalar(select(func.count()).select_from(Subscriber)) == 1
    record = await db_session.scalar(select(Subscriber))
    assert record.email == "reader@example.com"
    created_at = record.created_at
    assert (
        await db_client.post("/api/v1/subscriptions", json={"email": "reader@example.com"})
    ).status_code == 202
    await db_session.refresh(record)
    assert record.created_at == created_at
    for role in ("editor", "author"):
        assert (
            await db_client.get("/api/v1/admin/subscriptions", headers=accounts[role]["headers"])
        ).status_code == 403
    response = await db_client.get(
        "/api/v1/admin/subscriptions?search=reader", headers=accounts["admin"]["headers"]
    )
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["total"] == 1
    assert response.json()["data"][0]["email"] == "reader@example.com"
