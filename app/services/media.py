from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import APIError
from app.models import Article, MediaAsset, User
from app.services.common import advisory_lock, transaction

MEDIA_LOCK = 730019


class ImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            self.urls.update(value for key, value in attrs if key == "src" and value)


def content_urls(content: str, featured: str | None) -> set[str]:
    parser = ImageParser()
    parser.feed(content)
    return parser.urls | ({featured} if featured else set())


def image_urls(article: Article) -> set[str]:
    return content_urls(article.content_html, article.featured_image)


async def saved_urls(session: AsyncSession) -> set[str]:
    result: set[str] = set()
    for content, featured in await session.execute(
        select(Article.content_html, Article.featured_image)
    ):
        result.update(content_urls(content, featured))
    return result


async def reconcile_media(session: AsyncSession, changed: set[str]) -> None:
    # Call after flushing an article change, while holding MEDIA_LOCK.
    if not changed:
        return
    used = await saved_urls(session)
    assets = await session.scalars(select(MediaAsset).where(MediaAsset.secure_url.in_(changed)))
    for asset in assets:
        if asset.secure_url in used:
            if asset.deleted or asset.deletion_pending:
                raise APIError(422, "image_deleted", "An image has expired. Upload it again.")
            asset.unused_since = None
        elif asset.unused_since is None:
            asset.unused_since = datetime.now(UTC)


def credentials(settings: Settings) -> tuple[str, httpx.BasicAuth]:
    if not (
        settings.cloudinary_cloud_name
        and settings.cloudinary_api_key
        and settings.cloudinary_api_secret
    ):
        raise APIError(
            503,
            "media_not_configured",
            "Image uploads are not configured on the backend",
        )
    cloud = settings.cloudinary_cloud_name
    if not all(c.isalnum() or c in "-_" for c in cloud):
        raise APIError(503, "media_not_configured", "Invalid Cloudinary configuration")
    return f"https://api.cloudinary.com/v1_1/{cloud}/image", httpx.BasicAuth(
        settings.cloudinary_api_key, settings.cloudinary_api_secret.get_secret_value()
    )


async def cloud_request(
    settings: Settings, action: str, data: dict[str, str], files: Any = None
) -> dict[str, Any]:
    base, auth = credentials(settings)
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(f"{base}/{action}", auth=auth, data=data, files=files)
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
    except (httpx.HTTPError, ValueError):
        raise APIError(
            503,
            "media_provider_unavailable",
            "Image service unavailable. Please try again.",
        ) from None


def image_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    raise APIError(422, "invalid_image", "Choose a JPEG, PNG, GIF, or WebP image")


async def upload_image(
    session: AsyncSession, actor: User, data: bytes, settings: Settings
) -> MediaAsset:
    credentials(settings)
    if not data or len(data) > min(settings.cloudinary_max_image_bytes, settings.max_body_bytes):
        raise APIError(413, "image_too_large", "Image exceeds the configured upload size limit")
    extension = image_type(data)
    # Persist before the external request, so timed-out uploads can still be cleaned up.
    asset = MediaAsset(
        public_id=f"blog_uploads/{uuid4().hex}",
        owner_id=actor.id,
        unused_since=datetime.now(UTC),
    )
    async with transaction(session):
        session.add(asset)
    result = await cloud_request(
        settings,
        "upload",
        {
            "public_id": asset.public_id,
            "overwrite": "false",
            "allowed_formats": "jpg,png,gif,webp",
        },
        {
            "file": (
                f"image.{extension}",
                data,
                f"image/{'jpeg' if extension == 'jpg' else extension}",
            )
        },
    )
    if result.get("resource_type") != "image" or not str(result.get("secure_url", "")).startswith(
        "https://"
    ):
        raise APIError(503, "invalid_media_response", "Image service returned an invalid response")
    async with transaction(session):
        asset.secure_url = result["secure_url"]
    return asset


async def cleanup_media(session: AsyncSession, settings: Settings) -> int:
    credentials(settings)
    cutoff = datetime.now(UTC) - timedelta(hours=settings.media_cleanup_grace_hours)
    count = 0
    # One asset per transaction limits lock duration and makes partial progress retryable.
    for _ in range(10):
        async with transaction(session):
            await advisory_lock(session, MEDIA_LOCK)
            asset = await session.scalar(
                select(MediaAsset)
                .where(
                    MediaAsset.deleted.is_(False),
                    MediaAsset.unused_since < cutoff,
                )
                .order_by(MediaAsset.unused_since)
                .limit(1)
                .with_for_update()
            )
            if asset is None:
                break
            if asset.secure_url and asset.secure_url in await saved_urls(session):
                asset.unused_since = None
                continue
            # Block stale editor saves before making an irreversible external request.
            # Failed/timed-out deletions remain eligible for retry on the next run.
            asset.deletion_pending = True
        result = await cloud_request(
            settings,
            "destroy",
            {
                "public_id": asset.public_id,
                "invalidate": "true",
            },
        )
        if result.get("result") not in {"ok", "not found"}:
            raise APIError(503, "media_cleanup_failed", "Image cleanup could not complete")
        async with transaction(session):
            asset.deleted = True
            count += 1
    return count


async def media_cleanup_worker(factory: Any, settings: Settings) -> None:
    """Each API process sweeps every 15 minutes; database locks coordinate workers."""
    import logging

    import anyio

    while True:
        await anyio.sleep(900)
        try:
            async with factory() as session:
                await cleanup_media(session, settings)
        except Exception:
            logging.getLogger(__name__).warning("media.cleanup_failed; will retry next sweep")
