from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.common import Input, Output, Pagination
from app.utils.validation import plain_text


class AuthorCreate(Input):
    name: str = Field(min_length=1, max_length=150)
    specialization: str = Field(min_length=1, max_length=10000)

    @field_validator("name", "specialization")
    @classmethod
    def text(cls, value: str) -> str:
        value = plain_text(value)
        if not value:
            raise ValueError("Author fields cannot be empty")
        return value


class AuthorUpdate(Input):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    specialization: str | None = Field(default=None, min_length=1, max_length=10000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def required_values(self) -> "AuthorUpdate":
        for key in self.model_fields_set:
            if getattr(self, key) is None:
                raise ValueError("Author fields cannot be null")
        if self.name is not None:
            self.name = AuthorCreate.text(self.name)
        if self.specialization is not None:
            self.specialization = AuthorCreate.text(self.specialization)
        return self


class AuthorFilters(Pagination):
    include_inactive: bool = False


class AuthorResponse(Output):
    id: UUID
    name: str
    specialization: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
