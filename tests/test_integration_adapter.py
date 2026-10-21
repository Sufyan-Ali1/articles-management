import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.nextjs import Revalidator


@pytest.mark.parametrize("failure", ["http", "timeout", "redirect", "none"])
async def test_revalidation_contract(
    settings: Settings, failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[httpx.Request] = []
    settings.nextjs_revalidation_enabled = True
    settings.nextjs_revalidation_url = "https://next.example/revalidate"
    settings.nextjs_revalidation_secret = SecretStr("secret-do-not-log" * 3)

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private remote detail", request=request)
        return httpx.Response(
            {"http": 500, "redirect": 307, "none": 200}[failure],
            headers={"Location": "https://other.example"},
        )

    identity = uuid4()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await Revalidator(settings, client).notify(
            "article.update", identity, ["old-slug", "new-slug"]
        )
    assert len(calls) == 1
    assert (
        calls[0].headers["Authorization"]
        == "Bearer " + settings.nextjs_revalidation_secret.get_secret_value()
    )
    payload = json.loads(calls[0].content)
    assert payload["article_id"] == str(identity)
    assert payload["slugs"] == ["new-slug", "old-slug"]
    assert "article:old-slug" in payload["tags"]
    assert "secret-do-not-log" not in caplog.text
    assert "private remote detail" not in caplog.text


async def test_disabled_revalidation(settings: Settings) -> None:
    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Disabled integration must not send HTTP requests")

    async with httpx.AsyncClient(transport=httpx.MockTransport(never)) as client:
        await Revalidator(settings, client).notify("article.publish", uuid4(), ["slug"])


async def test_long_slugs_produce_bounded_cache_tags(settings: Settings) -> None:
    calls = []
    settings.nextjs_revalidation_enabled = True
    settings.nextjs_revalidation_url = "https://next.example/revalidate"
    settings.nextjs_revalidation_secret = SecretStr("test-only-secret" * 3)

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await Revalidator(settings, client).notify("article.update", uuid4(), ["x" * 350])
    assert all(len(tag) <= 256 for tag in calls[0]["tags"])
    assert calls[0]["slugs"] == ["x" * 350]
