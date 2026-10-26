import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContactMessage
from app.schemas.contacts import ContactCreate
from app.services.common import transaction
from app.services.requests import SubmissionGuard


async def submit_contact(
    session: AsyncSession, data: ContactCreate, ip: str, guard: SubmissionGuard
) -> None:
    if data.bot_field:
        return
    values = data.model_dump(exclude={"bot_field", "form_name"})
    values["name"] = data.name or None
    values["article_url"] = data.article_url if data.reason == "correction" else None
    fingerprint = hashlib.sha256(
        ("contact\0" + ip + "\0" + json.dumps(values, sort_keys=True)).encode()
    ).hexdigest()

    async def save() -> None:
        async with transaction(session):
            session.add(ContactMessage(**values))

    await guard.submit(fingerprint, save)
