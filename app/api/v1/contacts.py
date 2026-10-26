from typing import Annotated, Any
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import or_, select

from app.api.dependencies import Admin, Session, public_api_access
from app.core.errors import APIError
from app.core.middleware import client_ip
from app.models import ContactMessage
from app.repositories.queries import get_record, list_records
from app.schemas.common import Data, Page, Pagination
from app.schemas.contacts import ContactAccepted, ContactCreate, ContactResponse
from app.services.contacts import submit_contact
from app.utils.pagination import page_response

router = APIRouter(tags=["Contact messages"])


async def contact_payload(request: Request) -> ContactCreate:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    payload: Any
    if media_type == "application/x-www-form-urlencoded":
        try:
            pairs = parse_qsl(
                (await request.body()).decode("utf-8"), keep_blank_values=True, max_num_fields=20
            )
        except (ValueError, UnicodeDecodeError):
            raise APIError(422, "validation_error", "Invalid contact form") from None
        if len({key for key, _ in pairs}) != len(pairs):
            raise APIError(422, "validation_error", "Duplicate form fields are not permitted")
        payload = dict(pairs)
    elif media_type == "application/json":
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise APIError(422, "validation_error", "Invalid JSON") from None
    else:
        raise APIError(415, "unsupported_media_type", "Use JSON or URL-encoded form data")
    try:
        return ContactCreate.model_validate(payload)
    except ValidationError as exc:
        errors = [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
        raise RequestValidationError(errors) from None


@router.post(
    "/contact-messages",
    dependencies=[Depends(public_api_access)],
    status_code=202,
    response_model=Data[ContactAccepted],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                content_type: {"schema": ContactCreate.model_json_schema()}
                for content_type in ("application/json", "application/x-www-form-urlencoded")
            },
        }
    },
)
async def submit(
    request: Request, session: Session, data: Annotated[ContactCreate, Depends(contact_payload)]
) -> Data[ContactAccepted]:
    await submit_contact(
        session, data, client_ip(request.scope), request.app.state.submission_guard
    )
    return Data(data=ContactAccepted())


@router.get("/admin/contact-messages", response_model=Page[ContactResponse])
async def listing(
    session: Session, actor: Admin, params: Annotated[Pagination, Query()]
) -> Page[ContactResponse]:
    query = select(ContactMessage)
    if params.search:
        escaped = params.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            or_(
                ContactMessage.name.ilike(f"%{escaped}%", escape="\\"),
                ContactMessage.email.ilike(f"%{escaped}%", escape="\\"),
                ContactMessage.message.ilike(f"%{escaped}%", escape="\\"),
            )
        )
    rows, total = await list_records(
        session,
        ContactMessage,
        params.model_copy(update={"search": None}),
        query=query,
        allowed={"created_at", "name", "email", "reason"},
    )
    return page_response([ContactResponse.model_validate(row) for row in rows], total, params)


@router.get("/admin/contact-messages/{id}", response_model=Data[ContactResponse])
async def detail(id: UUID, session: Session, actor: Admin) -> Data[ContactResponse]:
    return Data(data=ContactResponse.model_validate(await get_record(session, ContactMessage, id)))
