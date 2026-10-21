import hashlib
import logging
from typing import Any
from uuid import UUID

import anyio
import httpx

from app.core.config import Settings


class Revalidator:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings, self.client = settings, client

    async def notify(self, event: str, entity_id: UUID, slugs: list[str] | None = None) -> None:
        if not self.settings.nextjs_revalidation_enabled:
            return
        assert self.settings.nextjs_revalidation_url and self.settings.nextjs_revalidation_secret
        tags = ["articles", "categories", "tags", "article-types"]
        if event.startswith("article."):
            tags.append(f"article:{entity_id}")
        tags.extend(
            f"article:{slug}"
            if len(slug) <= 248
            else f"article-slug-sha256:{hashlib.sha256(slug.encode()).hexdigest()}"
            for slug in sorted(set(slugs or []))
        )
        payload: dict[str, Any] = {
            "event": event,
            "entity_id": str(entity_id),
            "article_id": str(entity_id) if event.startswith("article.") else None,
            "slugs": sorted(set(slugs or [])),
            "tags": tags,
        }
        try:
            with anyio.fail_after(5):
                async with self.client.stream(
                    "POST",
                    self.settings.nextjs_revalidation_url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.settings.nextjs_revalidation_secret.get_secret_value()}"
                    },
                    timeout=httpx.Timeout(5, connect=2),
                    follow_redirects=False,
                ) as response:
                    response.raise_for_status()
        except (httpx.HTTPError, TimeoutError):
            # Neither exception messages nor URLs/response bodies are safe to log here.
            logging.getLogger(__name__).warning(
                "nextjs.revalidation_failed event=%s entity_id=%s", event, entity_id
            )
