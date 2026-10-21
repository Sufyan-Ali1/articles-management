from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.common import Input, Output, RequestStatus
from app.schemas.users import Email
from app.utils.validation import plain_text


class RequestCreate(Input):
    topic: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    name: str | None = Field(default=None, max_length=150)
    email: Email | None = None
    website: str = Field(default="", max_length=2048, description="Honeypot; leave empty")

    @field_validator("topic", "description", "name")
    @classmethod
    def no_markup(cls, value: str | None) -> str | None:
        return plain_text(value) if value is not None else None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return value.lower() if value is not None else None


class RequestUpdate(Input):
    status: RequestStatus | None = None
    admin_notes: str | None = Field(default=None, max_length=10000)

    @field_validator("admin_notes")
    @classmethod
    def no_markup(cls, value: str | None) -> str | None:
        return plain_text(value) if value is not None else None

    @model_validator(mode="after")
    def not_null_status(self) -> "RequestUpdate":
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Status cannot be null")
        return self


class RequestResponse(Output):
    id: UUID
    topic: str
    description: str | None
    name: str | None
    email: str | None
    status: RequestStatus
    admin_notes: str | None
    reviewed_by: UUID | None
    created_at: datetime
    updated_at: datetime


class SubmissionResponse(Output):
    message: str = "Thank you for your suggestion."
