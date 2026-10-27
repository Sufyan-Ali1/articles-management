import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import APIError
from app.core.limits import Limit, RateLimiter
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.schemas.common import ArticleFilters, PublicArticleFilters
from app.schemas.content import ArticleUpdate
from app.schemas.requests import RequestCreate, RequestUpdate
from app.schemas.users import UserCreate
from app.utils.validation import plain_text, safe_url, slugify, validate_jsonld


async def test_argon2id() -> None:
    encoded = await hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert await verify_password(encoded, "correct horse battery staple")
    assert not await verify_password(encoded, "wrong")
    assert not await verify_password("invalid hash", "wrong")


def test_jwt(settings: Settings) -> None:
    identity = uuid4()
    token = create_token(identity, settings)
    assert decode_token(token, settings)["sub"] == str(identity)


@pytest.mark.parametrize(
    "change", ["expired", "signature", "audience", "issuer", "subject", "algorithm", "missing_exp"]
)
def test_invalid_jwt(settings: Settings, change: str) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    key, algorithm = settings.jwt_secret.get_secret_value(), "HS256"
    if change == "expired":
        payload["exp"] = now - timedelta(seconds=1)
    elif change == "signature":
        key = "wrong" * 12
    elif change == "audience":
        payload["aud"] = "wrong"
    elif change == "issuer":
        payload["iss"] = "wrong"
    elif change == "subject":
        payload["sub"] = "not-a-uuid"
    elif change == "algorithm":
        algorithm = "HS384"
    elif change == "missing_exp":
        del payload["exp"]
    with pytest.raises(APIError) as caught:
        decode_token(jwt.encode(payload, key, algorithm=algorithm), settings)
    assert caught.value.status == 401


@pytest.mark.parametrize(
    "value",
    [
        "<script>alert(1)</script>",
        "<b>text</b>",
        "&lt;script&gt;bad&lt;/script&gt;",
        "<!--comment-->",
        "<img src=x onerror=alert(1)>",
        "hi\x00there",
    ],
)
def test_request_rejects_markup(value: str) -> None:
    with pytest.raises(ValidationError):
        RequestCreate(topic=value)
    with pytest.raises(ValidationError):
        RequestUpdate(admin_notes=value)


@pytest.mark.parametrize(
    "data",
    [
        {"topic": " "},
        {"topic": "x" * 301},
        {"topic": "Valid", "email": "invalid"},
        {"topic": "Valid", "status": "completed"},
        {"topic": "Valid", "admin_notes": "injected"},
        {"topic": "Valid", "reviewed_by": str(uuid4())},
    ],
)
def test_public_request_validation(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RequestCreate.model_validate(data)


def test_plain_text_and_slug() -> None:
    assert plain_text("  Explain 1 < 2 in Python  ") == "Explain 1 < 2 in Python"
    assert slugify("  Laptop repair: A guide! ", 180) == "laptop-repair-a-guide"
    with pytest.raises(ValueError):
        slugify("💻", 180)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:image/svg+xml,bad",
        "file:///etc/passwd",
        "//evil.example/x",
        "https://user:pass@example.com",
        "https://example.com/\nscript",
        "https://example.com:bad",
        "https://example.com\\@evil.example",
    ],
)
def test_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        safe_url(url)


def test_jsonld_validation() -> None:
    value = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "A laptop",
        "image": "https://example.com/laptop.png",
    }
    assert validate_jsonld(value) == value
    graph = {
        "@context": "https://schema.org",
        "@graph": [{"@type": "Article"}, {"@type": "Person"}],
    }
    assert validate_jsonld(graph) == graph


@pytest.mark.parametrize(
    "value",
    [
        {"@context": "https://evil.example", "@type": "Article"},
        {"@context": "https://schema.org"},
        {"@context": "https://schema.org", "@type": "javascript:bad"},
        {"@context": "https://schema.org", "@type": "Article", "image": "data:text/html,bad"},
        {"@context": "https://schema.org", "@graph": []},
        {"@context": "https://schema.org", "@type": "Article", "@import": "https://evil.example"},
    ],
)
def test_bad_jsonld(value: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        validate_jsonld(value)


def test_schema_and_mass_assignment() -> None:
    with pytest.raises(ValidationError):
        ArticleUpdate(view_count=99)
    with pytest.raises(ValidationError):
        ArticleUpdate(category_ids=[uuid4(), uuid4()], created_by_id=uuid4())
    with pytest.raises(ValidationError):
        ArticleUpdate(title=None)
    assert ArticleUpdate(excerpt=None).model_dump(exclude_unset=True) == {"excerpt": None}
    with pytest.raises(ValidationError):
        UserCreate(name="Admin", email="admin@example.com", password="short")
    with pytest.raises(ValidationError):
        PublicArticleFilters(status="draft")
    with pytest.raises(ValidationError):
        ArticleFilters(published_from="2026-01-01T00:00:00")
    with pytest.raises(ValidationError):
        ArticleFilters(published_from="2026-02-01T00:00:00Z", published_to="2026-01-01T00:00:00Z")


async def test_limiter_is_atomic_and_bounded() -> None:
    limiter = RateLimiter(max_keys=1)

    async def attempt() -> bool:
        try:
            await limiter.check(Limit("same", 5, 60))
            return True
        except APIError:
            return False

    assert sum(await asyncio.gather(*(attempt() for _ in range(30)))) == 5
    with pytest.raises(APIError):
        await limiter.check(Limit("different", 1, 60))
    assert len(limiter._entries) == 1


async def test_limiter_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.core import limits

    clock = [100.0]
    monkeypatch.setattr(limits, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    limiter = RateLimiter(max_keys=1)
    await limiter.check(Limit("key", 1, 10))
    with pytest.raises(APIError):
        await limiter.check(Limit("key", 1, 10))
    clock[0] += 11
    await limiter.check(Limit("key", 1, 10))


@pytest.mark.parametrize(
    "changes",
    [
        {"jwt_secret": "short"},
        {"cors_origins": ["*"]},
        {"database_url": "sqlite:///unsafe"},
        {
            "environment": "production",
            "nextjs_revalidation_enabled": True,
            "nextjs_revalidation_url": "http://example.com/revalidate",
            "nextjs_revalidation_secret": "x" * 48,
        },
    ],
)
def test_insecure_settings(settings: Settings, changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(settings.model_dump() | changes)
