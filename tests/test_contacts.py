from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.models import ContactMessage
from app.schemas.contacts import ContactCreate

PAYLOAD = {
    "name": " Reader ",
    "email": "Reader@Example.com",
    "reason": "correction",
    "article_url": "https://askandexplore.com/articles/example",
    "message": "Please check this passage.",
    "bot-field": "",
    "form-name": "contact",
}


def test_contact_validation():
    contact = ContactCreate.model_validate(PAYLOAD)
    assert contact.name == "Reader"
    assert contact.email == "reader@example.com"
    for changes in (
        {"email": "bad"},
        {"reason": "other"},
        {"message": "  "},
        {"message": "x" * 5001},
        {"message": "<script>alert(1)</script>"},
        {"name": "<b>Reader</b>"},
        {"article_url": "javascript:alert(1)"},
        {"article_url": "https://user:pass@example.com"},
        {"form-name": "other"},
    ):
        with pytest.raises(ValidationError):
            ContactCreate.model_validate({**PAYLOAD, **changes})
    minimal = ContactCreate(email="reader@example.com", reason="general", message="Hello")
    assert minimal.name == minimal.article_url == minimal.bot_field == ""


async def test_contact_accepts_json_and_form(client, monkeypatch):
    from app.api.v1 import contacts

    save = AsyncMock()
    monkeypatch.setattr(contacts, "submit_contact", save)
    for kwargs in ({"json": PAYLOAD}, {"data": PAYLOAD}):
        response = await client.post("/api/v1/contact-messages", **kwargs)
        assert response.status_code == 202, response.text
        assert response.json() == {"data": {"message": "Thank you for getting in touch."}}
        assert response.headers["cache-control"] == "no-store"
    assert save.await_count == 2
    assert save.call_args.args[1].email == "reader@example.com"
    assert (await client.get("/api/v1/admin/contact-messages")).status_code == 401
    document = (await client.get("/openapi.json")).json()
    content = document["paths"]["/api/v1/contact-messages"]["post"]["requestBody"]["content"]
    assert set(content) == {"application/json", "application/x-www-form-urlencoded"}


async def test_contact_rejects_bad_payloads(client):
    response = await client.post(
        "/api/v1/contact-messages", json={**PAYLOAD, "email": "private-invalid-email"}
    )
    assert response.status_code == 422
    assert "private-invalid-email" not in response.text
    assert (
        await client.post(
            "/api/v1/contact-messages", content="{}", headers={"Content-Type": "text/plain"}
        )
    ).status_code == 415
    assert (
        await client.post(
            "/api/v1/contact-messages", content="{", headers={"Content-Type": "application/json"}
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/v1/contact-messages",
            content="email=a&email=b",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    ).status_code == 422


async def test_contact_honeypot_and_limits(client):
    responses = [
        await client.post("/api/v1/contact-messages", json={**PAYLOAD, "bot-field": "spam"})
        for _ in range(6)
    ]
    assert all(response.status_code == 202 for response in responses[:5])
    assert responses[-1].status_code == 429


@pytest.mark.integration
async def test_contact_storage_and_permissions(db_client, db_session, accounts):
    responses = [await db_client.post("/api/v1/contact-messages", json=PAYLOAD) for _ in range(2)]
    assert all(response.status_code == 202 for response in responses)
    assert await db_session.scalar(select(func.count()).select_from(ContactMessage)) == 1
    record = await db_session.scalar(select(ContactMessage))
    assert record.email == "reader@example.com"
    assert record.article_url == PAYLOAD["article_url"]
    assert record.name == "Reader"
    for role in ("editor", "author"):
        assert (
            await db_client.get("/api/v1/admin/contact-messages", headers=accounts[role]["headers"])
        ).status_code == 403
    listing = await db_client.get(
        "/api/v1/admin/contact-messages?search=passage", headers=accounts["admin"]["headers"]
    )
    assert listing.status_code == 200
    assert listing.json()["meta"]["total"] == 1
    detail = await db_client.get(
        f"/api/v1/admin/contact-messages/{record.id}", headers=accounts["admin"]["headers"]
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["message"] == PAYLOAD["message"]
