from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")
Role = Literal["admin", "editor", "author"]
ArticleStatus = Literal["draft", "published", "archived", "scheduled"]
RequestStatus = Literal["pending", "accepted", "rejected", "completed"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Data(BaseModel, Generic[T]):
    data: T


class Meta(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class Page(BaseModel, Generic[T]):
    data: list[T]
    meta: Meta


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class Pagination(Input):
    page: int = Field(default=1, ge=1, le=100000)
    page_size: int = Field(default=20, ge=1, le=100)
    sort: str = Field(default="-created_at", max_length=40)
    search: str | None = Field(default=None, max_length=200)


class PublicArticleFilters(Pagination):
    sort: str = Field(default="-published_at", max_length=40)
    category: str | None = Field(default=None, max_length=180)
    tag: str | None = Field(default=None, max_length=180)
    article_type: str | None = Field(default=None, max_length=180)
    is_featured: bool | None = None
    published_from: datetime | None = None
    published_to: datetime | None = None

    @field_validator("published_from", "published_to")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Use timezone-aware timestamps")
        return value

    @model_validator(mode="after")
    def dates(self) -> "PublicArticleFilters":
        if self.published_from and self.published_to and self.published_from > self.published_to:
            raise ValueError("Publication date bounds are reversed")
        return self


class ID(Output):
    id: UUID


class ArticleFilters(PublicArticleFilters):
    sort: str = Field(default="-created_at", max_length=40)
    status: ArticleStatus | None = None
