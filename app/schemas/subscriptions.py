from datetime import datetime
from uuid import UUID

from pydantic import field_validator

from app.schemas.common import Input, Output
from app.schemas.users import Email


class SubscriptionCreate(Input):
    email: Email

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class SubscriptionAccepted(Output):
    message: str = "Thank you for subscribing."


class SubscriptionResponse(Output):
    id: UUID
    email: str
    created_at: datetime
