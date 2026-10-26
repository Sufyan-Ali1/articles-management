from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.schemas.common import ArticleStatus, Input, Output
from app.schemas.users import AuthorResponse
from app.utils.validation import safe_url, validate_jsonld, validate_slug


class ClassificationCreate(Input):
    name: str = Field(min_length=1, max_length=150)
    slug: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=10000)
    is_active: bool = True

    @field_validator("slug")
    @classmethod
    def check_slug(cls, value: str | None) -> str | None:
        return validate_slug(value) if value is not None else None


class CategoryCreate(ClassificationCreate):
    parent_id: UUID | None = None


class ClassificationUpdate(Input):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    slug: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=10000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def check_required(self) -> "ClassificationUpdate":
        for key in self.model_fields_set & {"name", "slug", "is_active"}:
            if getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        if self.slug is not None:
            validate_slug(self.slug)
        return self


class CategoryUpdate(ClassificationUpdate):
    parent_id: UUID | None = None


class ClassificationResponse(Output):
    id: UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryResponse(ClassificationResponse):
    parent_id: UUID | None


class ArticleFields(Input):
    excerpt: str | None = Field(default=None, max_length=10000)
    featured_image: str | None = Field(default=None, max_length=2048)
    featured_image_alt: str | None = Field(default=None, max_length=300)
    meta_title: str | None = Field(default=None, max_length=300)
    meta_description: str | None = Field(default=None, max_length=10000)
    schema_data: dict[str, Any] | None = Field(default=None, alias="schema")

    @field_validator("featured_image")
    @classmethod
    def url(cls, value: str | None) -> str | None:
        return safe_url(value) if value is not None else None

    @field_validator("schema_data")
    @classmethod
    def jsonld(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return validate_jsonld(value) if value is not None else None


class ArticleCreate(ArticleFields):
    title: str = Field(min_length=1, max_length=300)
    slug: str | None = Field(default=None, min_length=1, max_length=350)
    content_html: str = Field(min_length=1, max_length=1000000)
    article_type_id: UUID
    category_ids: list[UUID] = Field(default_factory=list, max_length=100)
    tag_ids: list[UUID] = Field(default_factory=list, max_length=100)
    is_featured: bool = False

    @field_validator("slug")
    @classmethod
    def slug_valid(cls, value: str | None) -> str | None:
        return validate_slug(value) if value is not None else None

    @field_validator("category_ids", "tag_ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Relationship IDs must be unique")
        return value


class ArticleUpdate(ArticleFields):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    slug: str | None = Field(default=None, min_length=1, max_length=350)
    content_html: str | None = Field(default=None, min_length=1, max_length=1000000)
    article_type_id: UUID | None = None
    category_ids: list[UUID] | None = Field(default=None, max_length=100)
    tag_ids: list[UUID] | None = Field(default=None, max_length=100)
    is_featured: bool | None = None
    status: ArticleStatus | None = None

    @model_validator(mode="after")
    def required_values(self) -> "ArticleUpdate":
        required = {
            "title",
            "slug",
            "content_html",
            "article_type_id",
            "category_ids",
            "tag_ids",
            "is_featured",
            "status",
        }
        if any(getattr(self, k) is None for k in self.model_fields_set & required):
            raise ValueError("Non-nullable article fields cannot be null")
        if self.slug is not None:
            validate_slug(self.slug)
        for ids in (self.category_ids, self.tag_ids):
            if ids is not None and len(set(ids)) != len(ids):
                raise ValueError("Relationship IDs must be unique")
        return self


class ArticleSchedule(Input):
    scheduled_publish_at: AwareDatetime

    @field_validator("scheduled_publish_at")
    @classmethod
    def future_time(cls, value: datetime) -> datetime:
        if value <= datetime.now(UTC):
            raise ValueError("Scheduled publication must be in the future")
        return value.astimezone(UTC)


class ArticleSummary(Output):
    id: UUID
    title: str
    slug: str
    excerpt: str | None
    featured_image: str | None
    featured_image_alt: str | None
    author: AuthorResponse | None
    article_type: ClassificationResponse | None
    categories: list[CategoryResponse]
    tags: list[ClassificationResponse]
    is_featured: bool
    view_count: int
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ArticleResponse(ArticleSummary):
    content_html: str
    meta_title: str | None
    meta_description: str | None
    schema_data: dict[str, Any] | None = Field(
        validation_alias="schema", serialization_alias="schema"
    )


class AdminArticleSummary(ArticleSummary):
    author_id: UUID | None
    article_type_id: UUID | None
    status: ArticleStatus
    scheduled_publish_at: datetime | None


class AdminArticleResponse(ArticleResponse):
    author_id: UUID | None
    article_type_id: UUID | None
    status: ArticleStatus
    scheduled_publish_at: datetime | None
