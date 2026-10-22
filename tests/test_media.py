from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.core.errors import APIError
from app.models import MediaAsset
from app.services import media


def configured(settings):
    settings.cloudinary_cloud_name = "test-cloud"
    settings.cloudinary_api_key = "test-key"
    settings.cloudinary_api_secret = SecretStr("test-secret")
    return settings


def session_for(asset, references=()):
    return SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
        add=Mock(),
        execute=AsyncMock(return_value=references),
        scalars=AsyncMock(return_value=[asset]),
        scalar=AsyncMock(side_effect=[asset, None]),
    )


def asset_record():
    return MediaAsset(
        public_id="blog_uploads/example",
        secure_url="https://res.cloudinary.com/test/image/upload/example.png",
        unused_since=datetime.now(UTC) - timedelta(days=2),
        deleted=False,
        deletion_pending=False,
    )


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\xff\xd8\xff", "jpg"),
        (b"GIF89a", "gif"),
        (b"RIFF0000WEBP", "webp"),
    ],
)
def test_supported_images(data, expected):
    assert media.image_type(data) == expected


def test_svg_and_arbitrary_files_rejected():
    for data in [b"<svg></svg>", b"hello", b"RIFF0000WAVE"]:
        with pytest.raises(APIError):
            media.image_type(data)


def test_extracts_featured_and_inline_images_with_entities():
    assert media.content_urls(
        '<img src="https://a.test/i?a=1&amp;b=2"><img src="/second"/>', "/featured"
    ) == {"https://a.test/i?a=1&b=2", "/second", "/featured"}


async def test_missing_configuration_is_explicit(settings):
    settings.cloudinary_cloud_name = None
    with pytest.raises(APIError) as error:
        await media.upload_image(
            session_for(None), SimpleNamespace(id=uuid4()), b"GIF89a", settings
        )
    assert error.value.code == "media_not_configured"


async def test_upload_records_asset_before_cloudinary_and_returns_url(settings, monkeypatch):
    session = session_for(None)
    cloud = AsyncMock(
        return_value={
            "resource_type": "image",
            "secure_url": "https://res.cloudinary.com/test/image.png",
        }
    )
    monkeypatch.setattr(media, "cloud_request", cloud)
    result = await media.upload_image(
        session, SimpleNamespace(id=uuid4()), b"GIF89a", configured(settings)
    )
    assert result.secure_url == "https://res.cloudinary.com/test/image.png"
    assert result.public_id.startswith("blog_uploads/")
    assert session.commit.await_count == 2
    assert result.unused_since is not None


async def test_oversize_image_never_reaches_cloudinary(settings, monkeypatch):
    settings = configured(settings)
    settings.cloudinary_max_image_bytes = 1024
    cloud = AsyncMock()
    monkeypatch.setattr(media, "cloud_request", cloud)
    with pytest.raises(APIError) as error:
        await media.upload_image(
            session_for(None), SimpleNamespace(id=uuid4()), b"GIF89a" + b"x" * 1024, settings
        )
    assert error.value.status == 413
    cloud.assert_not_awaited()


async def test_shared_saved_image_is_retained(settings, monkeypatch):
    asset = asset_record()
    session = session_for(asset, [(f'<img src="{asset.secure_url}">', None)])
    monkeypatch.setattr(media, "advisory_lock", AsyncMock())
    cloud = AsyncMock()
    monkeypatch.setattr(media, "cloud_request", cloud)
    assert await media.cleanup_media(session, configured(settings)) == 0
    assert asset.unused_since is None
    cloud.assert_not_awaited()


async def test_saved_removal_starts_grace_period():
    asset = asset_record()
    asset.unused_since = None
    await media.reconcile_media(session_for(asset), {asset.secure_url})
    assert asset.unused_since >= datetime.now(UTC) - timedelta(seconds=1)


async def test_failed_deletion_stays_retryable_and_blocks_stale_save(settings, monkeypatch):
    asset = asset_record()
    session = session_for(asset)
    monkeypatch.setattr(media, "advisory_lock", AsyncMock())
    cloud = AsyncMock(side_effect=APIError(503, "unavailable", "Try again"))
    monkeypatch.setattr(media, "cloud_request", cloud)
    with pytest.raises(APIError):
        await media.cleanup_media(session, configured(settings))
    assert asset.deletion_pending and not asset.deleted
    with pytest.raises(APIError) as error:
        await media.reconcile_media(
            session_for(asset, [("", asset.secure_url)]), {asset.secure_url}
        )
    assert error.value.code == "image_deleted"
    cloud.side_effect = None
    cloud.return_value = {"result": "not found"}
    assert await media.cleanup_media(session_for(asset), settings) == 1
    assert asset.deleted
    assert cloud.call_args.args[2]["invalidate"] == "true"


async def test_media_routes_require_authentication(client: httpx.AsyncClient):
    assert (await client.post("/api/v1/media/images", content=b"GIF89a")).status_code == 401
    assert (await client.post("/api/v1/media/cleanup")).status_code == 401
