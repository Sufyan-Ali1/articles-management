import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from app.core.config import Settings, get_settings
from app.core.security import create_token, hash_password
from app.db.session import create_database
from app.main import create_app
from app.models import ArticleType, User
from scripts.seed_types import seed

PASSWORD = "integration-test-only-passphrase"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://127.0.0.1:59999/unavailable_test",
        jwt_secret=secrets.token_urlsafe(48),
    )


@pytest.fixture
async def application(settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(application: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as result:
        yield result


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test")
    if not url.startswith("postgresql+asyncpg://") or not urlsplit(url).path.endswith("_test"):
        pytest.fail(
            "TEST_DATABASE_URL must use asyncpg and a dedicated database name ending in _test"
        )
    previous = {k: os.environ.get(k) for k in ("DATABASE_URL", "JWT_SECRET", "ENVIRONMENT")}
    os.environ.update(DATABASE_URL=url, JWT_SECRET=secrets.token_urlsafe(48), ENVIRONMENT="test")
    get_settings.cache_clear()
    try:
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        command.check(config)
        yield url
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


@pytest.fixture
async def db_settings(migrated_database: str) -> Settings:
    return Settings(
        environment="test",
        database_url=migrated_database,
        jwt_secret=secrets.token_urlsafe(48),
        mutations_per_minute=1000,
        login_account_per_minute=20,
    )


@pytest.fixture
async def db_app(db_settings: Settings) -> AsyncIterator[FastAPI]:
    engine, factory = create_database(db_settings)
    async with factory() as session:
        await session.execute(
            text(
                "TRUNCATE article_requests, admin_logs, article_tags, article_categories, articles, categories, tags, article_types, users CASCADE"
            )
        )
        await session.commit()
    await engine.dispose()
    app = create_app(db_settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def db_client(db_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=db_app), base_url="http://test"
    ) as result:
        yield result


@pytest.fixture
async def db_session(db_app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with db_app.state.session_factory() as session:
        yield session


@pytest.fixture
async def accounts(db_app: FastAPI, db_session: AsyncSession) -> dict[str, Any]:
    encoded = await hash_password(PASSWORD)
    result: dict[str, Any] = {}
    for role in ("admin", "editor", "author", "other"):
        user = User(
            name=role.title(),
            email=f"{role}@example.com",
            role="author" if role == "other" else role,
            password_hash=encoded,
            is_active=True,
        )
        db_session.add(user)
        await db_session.flush()
        result[role] = {
            "user": user,
            "headers": {"Authorization": "Bearer " + create_token(user.id, db_app.state.settings)},
        }
    await seed(db_session)
    await db_session.commit()
    result["type_id"] = str(
        await db_session.scalar(
            __import__("sqlalchemy").select(ArticleType.id).where(ArticleType.slug == "tutorial")
        )
    )
    return result


@pytest.fixture
async def draft(db_client: httpx.AsyncClient, accounts: dict[str, Any]) -> dict[str, Any]:
    pytest.importorskip("nh3", reason="Article HTML tests require the nh3 runtime dependency")
    response = await db_client.post(
        "/api/v1/articles",
        headers=accounts["author"]["headers"],
        json={
            "title": "Repair a laptop",
            "content_html": "<p>A real repair guide.</p>",
            "article_type_id": accounts["type_id"],
            "schema": {
                "@context": "https://schema.org",
                "@type": "TechArticle",
                "headline": "Repair a laptop",
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]
