import asyncio
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_token
from app.integrations.nextjs import Revalidator
from app.models import AdminLog, Article, ArticleRequest, ArticleType, User
from scripts.seed_types import seed
from tests.conftest import PASSWORD

pytestmark = pytest.mark.integration


async def test_database_schema_and_seed(db_session: AsyncSession) -> None:
    names = set(
        (
            await db_session.scalars(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        ).all()
    )
    assert names - {"alembic_version"} == {
        "users",
        "refresh_sessions",
        "articles",
        "categories",
        "tags",
        "article_types",
        "article_categories",
        "article_tags",
        "admin_logs",
        "article_requests",
    }
    await seed(db_session)
    await seed(db_session)
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(ArticleType)) == 7


async def test_authentication(db_client: httpx.AsyncClient, accounts: dict[str, Any]) -> None:
    response = await db_client.post(
        "/api/v1/auth/login", json={"email": "AUTHOR@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    response = await db_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token})
    assert response.json()["data"]["role"] == "author"
    assert "password_hash" not in response.text
    for email in ("author@example.com", "missing@example.com"):
        response = await db_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Invalid email or password"
    assert (
        await db_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"})
    ).status_code == 401


@pytest.mark.parametrize("role", ["admin", "editor", "author"])
async def test_management_permissions(
    db_client: httpx.AsyncClient, accounts: dict[str, Any], role: str
) -> None:
    headers = accounts[role]["headers"]
    for path in ("/users", "/admin-logs"):
        assert (await db_client.get("/api/v1" + path, headers=headers)).status_code == (
            200 if role == "admin" else 403
        )
    response = await db_client.get("/api/v1/admin/article-requests", headers=headers)
    assert response.status_code == (403 if role == "author" else 200)
    for path in ("/categories", "/tags", "/article-types"):
        response = await db_client.post(
            "/api/v1" + path, headers=headers, json={"name": "New classification"}
        )
        assert response.status_code == (201 if role == "admin" else 403), response.text


async def test_users_last_admin_and_deactivation(
    db_client: httpx.AsyncClient, accounts: dict[str, Any], db_session: AsyncSession
) -> None:
    admin = accounts["admin"]
    own_id = str(admin["user"].id)
    for body in ({"role": "author"}, {"is_active": False}):
        assert (
            await db_client.patch(f"/api/v1/users/{own_id}", headers=admin["headers"], json=body)
        ).status_code == 409
    assert (
        await db_client.delete(f"/api/v1/users/{own_id}", headers=admin["headers"])
    ).status_code == 409
    author = accounts["author"]
    response = await db_client.delete(
        f"/api/v1/users/{author['user'].id}", headers=admin["headers"]
    )
    assert response.status_code == 204
    assert (await db_client.get("/api/v1/auth/me", headers=author["headers"])).status_code == 401
    assert (
        await db_client.post(
            "/api/v1/auth/login", json={"email": "author@example.com", "password": PASSWORD}
        )
    ).status_code == 401
    await db_session.refresh(author["user"])
    assert not author["user"].is_active
    assert await db_session.scalar(select(func.count()).select_from(User)) == 4


async def test_concurrent_admin_deactivation(
    db_client: httpx.AsyncClient,
    db_app: FastAPI,
    accounts: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    author = accounts["author"]["user"]
    author.role = "admin"
    await db_session.commit()
    headers = {"Authorization": "Bearer " + create_token(author.id, db_app.state.settings)}
    original = accounts["admin"]
    responses = await asyncio.gather(
        db_client.delete(f"/api/v1/users/{original['user'].id}", headers=original["headers"]),
        db_client.delete(f"/api/v1/users/{author.id}", headers=headers),
    )
    assert sorted(r.status_code for r in responses) == [204, 409]
    assert (
        await db_session.scalar(
            select(func.count()).select_from(User).where(User.role == "admin", User.is_active)
        )
        == 1
    )


@pytest.mark.parametrize("path", ["categories", "tags", "article-types"])
async def test_classification_crud(
    db_client: httpx.AsyncClient, accounts: dict[str, Any], path: str
) -> None:
    headers = accounts["admin"]["headers"]
    response = await db_client.post(
        f"/api/v1/{path}", headers=headers, json={"name": "Electronics", "description": "Devices"}
    )
    assert response.status_code == 201, response.text
    row = response.json()["data"]
    assert (await db_client.get(f"/api/v1/{path}/{row['slug']}")).status_code == 200
    assert (
        await db_client.post(f"/api/v1/{path}", headers=headers, json={"name": "Electronics"})
    ).status_code == 409
    response = await db_client.patch(
        f"/api/v1/{path}/{row['id']}",
        headers=headers,
        json={"description": None, "is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["data"]["description"] is None
    assert (await db_client.get(f"/api/v1/{path}/{row['slug']}")).status_code == 404
    assert (
        await db_client.delete(f"/api/v1/{path}/{row['id']}", headers=headers)
    ).status_code == 204


async def test_category_cycles(db_client: httpx.AsyncClient, accounts: dict[str, Any]) -> None:
    headers = accounts["admin"]["headers"]
    parent = (
        await db_client.post("/api/v1/categories", headers=headers, json={"name": "Parent"})
    ).json()["data"]
    child = (
        await db_client.post(
            "/api/v1/categories", headers=headers, json={"name": "Child", "parent_id": parent["id"]}
        )
    ).json()["data"]
    for target in (parent["id"], child["id"]):
        response = await db_client.patch(
            f"/api/v1/categories/{parent['id']}", headers=headers, json={"parent_id": target}
        )
        assert response.status_code == 409
    assert (
        await db_client.delete(f"/api/v1/categories/{parent['id']}", headers=headers)
    ).status_code == 409
    assert (
        await db_client.patch(
            f"/api/v1/categories/{child['id']}", headers=headers, json={"parent_id": None}
        )
    ).status_code == 200
    assert (
        await db_client.delete(f"/api/v1/categories/{parent['id']}", headers=headers)
    ).status_code == 204


async def test_concurrent_category_cycle(
    db_client: httpx.AsyncClient, accounts: dict[str, Any]
) -> None:
    headers = accounts["admin"]["headers"]
    ids = [
        (await db_client.post("/api/v1/categories", headers=headers, json={"name": name})).json()[
            "data"
        ]["id"]
        for name in ("A", "B")
    ]
    responses = await asyncio.gather(
        *(
            db_client.patch(
                f"/api/v1/categories/{ids[i]}", headers=headers, json={"parent_id": ids[1 - i]}
            )
            for i in range(2)
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 409]


async def test_article_workflow(
    db_client: httpx.AsyncClient, accounts: dict[str, Any], draft: dict[str, Any]
) -> None:
    identity, slug = draft["id"], draft["slug"]
    author, editor = accounts["author"]["headers"], accounts["editor"]["headers"]
    assert (await db_client.get(f"/api/v1/articles/{slug}")).status_code == 404
    assert (await db_client.get("/api/v1/articles")).json()["meta"]["total"] == 0
    assert (
        await db_client.get(
            f"/api/v1/admin/articles/{identity}", headers=accounts["other"]["headers"]
        )
    ).status_code == 404
    assert (
        await db_client.patch(
            f"/api/v1/articles/{identity}",
            headers=accounts["other"]["headers"],
            json={"title": "Steal"},
        )
    ).status_code == 404
    assert (
        await db_client.patch(
            f"/api/v1/articles/{identity}", headers=author, json={"excerpt": "Updated"}
        )
    ).status_code == 200
    assert (
        await db_client.post(f"/api/v1/articles/{identity}/publish", headers=author)
    ).status_code == 403
    response = await db_client.post(f"/api/v1/articles/{identity}/publish", headers=editor)
    assert response.status_code == 200, response.text
    date = response.json()["data"]["published_at"]
    assert (
        await db_client.patch(f"/api/v1/articles/{identity}", headers=author, json={"title": "No"})
    ).status_code == 403
    response = await db_client.get(f"/api/v1/articles/{slug}")
    assert response.status_code == 200
    assert response.json()["data"]["view_count"] == 1
    assert "email" not in response.json()["data"]["author"]
    response = await db_client.patch(
        f"/api/v1/articles/{identity}",
        headers=editor,
        json={"title": "Updated title", "slug": "new-slug"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["published_at"] == date
    assert (await db_client.get(f"/api/v1/articles/{slug}")).status_code == 404
    assert (
        await db_client.post(f"/api/v1/articles/{identity}/unpublish", headers=editor)
    ).status_code == 200
    assert (await db_client.get("/api/v1/articles/new-slug")).status_code == 404
    assert (await db_client.post(f"/api/v1/articles/{identity}/publish", headers=editor)).json()[
        "data"
    ]["published_at"] == date
    assert (
        await db_client.patch(
            f"/api/v1/articles/{identity}", headers=editor, json={"status": "archived"}
        )
    ).status_code == 200
    assert (await db_client.get("/api/v1/articles/new-slug")).status_code == 404
    assert (
        await db_client.patch(
            f"/api/v1/articles/{identity}", headers=editor, json={"status": "draft"}
        )
    ).status_code == 200
    assert (
        await db_client.delete(f"/api/v1/articles/{identity}", headers=editor)
    ).status_code == 403
    assert (
        await db_client.delete(f"/api/v1/articles/{identity}", headers=accounts["admin"]["headers"])
    ).status_code == 204


async def test_relationships_public_filters_and_rollback(
    db_client: httpx.AsyncClient,
    accounts: dict[str, Any],
    draft: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    admin, editor = accounts["admin"]["headers"], accounts["editor"]["headers"]
    category = (
        await db_client.post("/api/v1/categories", headers=admin, json={"name": "Laptops"})
    ).json()["data"]
    tag = (await db_client.post("/api/v1/tags", headers=admin, json={"name": "Repair"})).json()[
        "data"
    ]
    path = f"/api/v1/articles/{draft['id']}"
    response = await db_client.patch(
        path,
        headers=editor,
        json={"category_ids": [category["id"]], "tag_ids": [tag["id"]], "is_featured": True},
    )
    assert response.status_code == 200, response.text
    assert (
        await db_client.delete(f"/api/v1/categories/{category['id']}", headers=admin)
    ).status_code == 409
    assert (await db_client.delete(f"/api/v1/tags/{tag['id']}", headers=admin)).status_code == 409
    assert (
        await db_client.delete(f"/api/v1/article-types/{accounts['type_id']}", headers=admin)
    ).status_code == 409
    assert (await db_client.get("/api/v1/articles?is_featured=true")).json()["meta"]["total"] == 0
    assert (
        await db_client.patch(path, headers=editor, json={"tag_ids": [tag["id"], tag["id"]]})
    ).status_code == 422
    assert (
        await db_client.patch(path, headers=editor, json={"tag_ids": [str(uuid4())]})
    ).status_code == 422
    await db_client.post(path + "/publish", headers=editor)
    response = await db_client.get(
        "/api/v1/articles",
        params={
            "category": "laptops",
            "tag": "repair",
            "article_type": "tutorial",
            "is_featured": True,
            "search": "laptop",
            "sort": "-view_count",
            "page_size": 1,
        },
    )
    assert response.json()["meta"]["total"] == 1
    assert "content_html" not in response.json()["data"][0]
    assert (await db_client.get("/api/v1/articles?sort=password_hash")).status_code == 422
    assert (await db_client.get("/api/v1/articles?status=draft")).status_code == 422
    assert (await db_client.get("/api/v1/articles?page_size=101")).status_code == 422
    assert (await db_client.get("/api/v1/articles?search=%25")).json()["meta"]["total"] == 0
    logs_before = await db_session.scalar(select(func.count()).select_from(AdminLog))
    response = await db_client.post(
        "/api/v1/articles",
        headers=editor,
        json={
            "title": "Duplicate",
            "slug": draft["slug"],
            "content_html": "<p>Duplicate</p>",
            "article_type_id": accounts["type_id"],
            "tag_ids": [tag["id"]],
        },
    )
    assert response.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(Article)) == 1
    assert await db_session.scalar(select(func.count()).select_from(AdminLog)) == logs_before
    await db_client.delete(path, headers=admin)
    assert (await db_client.get("/api/v1/tags/repair")).status_code == 200
    assert (await db_client.delete(f"/api/v1/tags/{tag['id']}", headers=admin)).status_code == 204


async def test_inactive_classifications_block_publication(
    db_client: httpx.AsyncClient, accounts: dict[str, Any], draft: dict[str, Any]
) -> None:
    response = await db_client.patch(
        f"/api/v1/article-types/{accounts['type_id']}",
        headers=accounts["admin"]["headers"],
        json={"is_active": False},
    )
    assert response.status_code == 200
    response = await db_client.post(
        f"/api/v1/articles/{draft['id']}/publish", headers=accounts["editor"]["headers"]
    )
    assert response.status_code == 422


async def test_concurrent_views(
    db_client: httpx.AsyncClient, accounts: dict[str, Any], draft: dict[str, Any]
) -> None:
    await db_client.post(
        f"/api/v1/articles/{draft['id']}/publish", headers=accounts["editor"]["headers"]
    )
    responses = await asyncio.gather(
        *(db_client.get(f"/api/v1/articles/{draft['slug']}") for _ in range(12))
    )
    assert all(r.status_code == 200 for r in responses)
    response = await db_client.get(
        f"/api/v1/admin/articles/{draft['id']}", headers=accounts["editor"]["headers"]
    )
    assert response.json()["data"]["view_count"] == 12


async def test_submission_review_and_audit(
    db_client: httpx.AsyncClient, accounts: dict[str, Any], db_session: AsyncSession
) -> None:
    payload = {
        "topic": "How to repair a laptop",
        "email": "reader@example.com",
        "description": "Explain charging faults",
    }
    response = await db_client.post("/api/v1/article-requests", json=payload)
    assert response.status_code == 202
    assert response.json() == {"data": {"message": "Thank you for your suggestion."}}
    assert (
        await db_client.post("/api/v1/article-requests", json=payload)
    ).json() == response.json()
    assert await db_session.scalar(select(func.count()).select_from(ArticleRequest)) == 1
    editor = accounts["editor"]["headers"]
    listing = await db_client.get(
        "/api/v1/admin/article-requests?status=pending&sort=topic&page_size=1", headers=editor
    )
    identity = listing.json()["data"][0]["id"]
    assert listing.json()["meta"]["total"] == 1
    assert (
        await db_client.get(
            f"/api/v1/admin/article-requests/{identity}", headers=accounts["author"]["headers"]
        )
    ).status_code == 403
    for status in ("accepted", "completed", "pending", "rejected", "accepted"):
        response = await db_client.patch(
            f"/api/v1/admin/article-requests/{identity}",
            headers=editor,
            json={"status": status, "admin_notes": "Reviewed privately"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == status
        assert response.json()["data"]["reviewed_by"] == str(accounts["editor"]["user"].id)
    assert (
        await db_client.patch(
            f"/api/v1/admin/article-requests/{identity}",
            headers=editor,
            json={"reviewed_by": str(uuid4())},
        )
    ).status_code == 422
    assert (
        await db_client.delete(f"/api/v1/admin/article-requests/{identity}", headers=editor)
    ).status_code == 403
    assert (
        await db_client.delete(
            f"/api/v1/admin/article-requests/{identity}", headers=accounts["admin"]["headers"]
        )
    ).status_code == 204
    logs = list(
        (
            await db_session.scalars(select(AdminLog).where(AdminLog.entity_id == UUID(identity)))
        ).all()
    )
    assert len(logs) == 6
    assert "reader@example.com" not in str([log.details for log in logs])
    assert "Reviewed privately" not in str([log.details for log in logs])


async def test_concurrent_submission_deduplication(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    responses = await asyncio.gather(
        *(
            db_client.post("/api/v1/article-requests", json={"topic": "Same topic"})
            for _ in range(5)
        )
    )
    assert all(r.status_code == 202 for r in responses)
    assert await db_session.scalar(select(func.count()).select_from(ArticleRequest)) == 1
    assert (
        await db_client.post("/api/v1/article-requests", json={"topic": "Another topic"})
    ).status_code == 429


async def test_revalidation_failure_commits(
    db_client: httpx.AsyncClient,
    db_app: FastAPI,
    accounts: dict[str, Any],
    draft: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    config = db_app.state.settings.model_copy(
        update={
            "nextjs_revalidation_enabled": True,
            "nextjs_revalidation_url": "https://next.example/revalidate",
        }
    )
    from pydantic import SecretStr

    config.nextjs_revalidation_secret = SecretStr("test-only-revalidation-secret" * 2)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ) as client:
        db_app.state.revalidator = Revalidator(config, client)
        response = await db_client.post(
            f"/api/v1/articles/{draft['id']}/publish", headers=accounts["editor"]["headers"]
        )
    assert response.status_code == 200
    article = await db_session.get(Article, UUID(draft["id"]))
    assert article.status == "published"
    assert (await db_client.get(f"/api/v1/articles/{draft['slug']}")).status_code == 200


async def test_readiness(db_client: httpx.AsyncClient) -> None:
    assert (await db_client.get("/ready")).status_code == 200


async def test_user_crud_and_private_fields(
    db_client: httpx.AsyncClient, accounts: dict[str, Any]
) -> None:
    headers = accounts["admin"]["headers"]
    payload = {
        "name": "New author",
        "email": "new-author@example.com",
        "password": PASSWORD,
        "role": "author",
    }
    response = await db_client.post("/api/v1/users", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    user = response.json()["data"]
    assert "password" not in response.text
    assert (await db_client.post("/api/v1/users", headers=headers, json=payload)).status_code == 409
    assert (
        await db_client.post("/api/v1/users", headers=accounts["author"]["headers"], json=payload)
    ).status_code == 403
    assert (await db_client.get(f"/api/v1/users/{user['id']}", headers=headers)).status_code == 200
    response = await db_client.patch(
        f"/api/v1/users/{user['id']}",
        headers=headers,
        json={"name": "Updated author", "role": "editor"},
    )
    assert response.json()["data"]["role"] == "editor"
    assert (await db_client.get("/api/v1/users?search=Updated&sort=email", headers=headers)).json()[
        "meta"
    ]["total"] == 1
    assert (
        await db_client.delete(f"/api/v1/users/{user['id']}", headers=headers)
    ).status_code == 204


@pytest.mark.parametrize("path", ["categories", "tags", "article-types"])
async def test_admin_can_manage_inactive_classifications(
    db_client: httpx.AsyncClient, accounts: dict[str, Any], path: str
) -> None:
    headers = accounts["admin"]["headers"]
    response = await db_client.post(
        f"/api/v1/{path}", headers=headers, json={"name": "Inactive item", "is_active": False}
    )
    assert response.status_code == 201
    row = response.json()["data"]
    assert (
        await db_client.get(f"/api/v1/{path}?include_inactive=true", headers=headers)
    ).status_code == 200
    assert (
        await db_client.get(f"/api/v1/{path}/{row['slug']}?include_inactive=true", headers=headers)
    ).status_code == 200
    assert (
        await db_client.get(
            f"/api/v1/{path}?include_inactive=true", headers=accounts["editor"]["headers"]
        )
    ).status_code == 403
