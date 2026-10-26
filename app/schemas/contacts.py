from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import Input, Output
from app.schemas.users import Email
from app.utils.validation import plain_text, safe_url

ContactReason = Literal["general", "correction", "privacy"]


class ContactCreate(Input):
    name: str = Field(default="", max_length=150)
    email: Email
    reason: ContactReason
    article_url: str = Field(default="", max_length=2048)
    message: str = Field(min_length=1, max_length=5000)
    bot_field: str = Field(default="", alias="bot-field", max_length=2048)
    form_name: Literal["contact"] = Field(default="contact", alias="form-name")

    @field_validator("name", "message")
    @classmethod
    def no_markup(cls, value: str) -> str:
        return plain_text(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("article_url")
    @classmethod
    def check_url(cls, value: str) -> str:
        return safe_url(value) if value else value


class ContactAccepted(Output):
    message: str = "Thank you for getting in touch."


class ContactResponse(Output):
    id: UUID
    name: str | None
    email: str
    reason: ContactReason
    article_url: str | None
    message: str
    created_at: datetime
