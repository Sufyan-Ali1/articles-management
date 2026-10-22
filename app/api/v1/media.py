from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.dependencies import Actor, Admin, Session
from app.core.errors import APIError
from app.schemas.common import Data
from app.services.media import cleanup_media, upload_image

router = APIRouter(tags=["Media"])


class MediaResponse(BaseModel):
    secure_url: str
    public_id: str


@router.post("/media/images", status_code=201, response_model=Data[MediaResponse])
async def upload(request: Request, session: Session, actor: Actor) -> Data[MediaResponse]:
    """Upload raw JPEG/PNG/GIF/WebP bytes with the corresponding image Content-Type."""
    settings = request.app.state.settings
    limit = min(settings.cloudinary_max_image_bytes, settings.max_body_bytes)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise APIError(413, "image_too_large", "Image exceeds the configured upload size limit")
    asset = await upload_image(session, actor, bytes(body), settings)
    return Data(data=MediaResponse(secure_url=asset.secure_url or "", public_id=asset.public_id))


@router.post("/media/cleanup", response_model=Data[dict[str, int]])
async def cleanup(request: Request, session: Session, actor: Admin) -> Data[dict[str, int]]:
    """Run periodically with admin authentication; deletes at most ten unused assets."""
    count = await cleanup_media(session, request.app.state.settings)
    return Data(data={"deleted": count})
