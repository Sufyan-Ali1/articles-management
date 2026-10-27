from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.common import Input, Output, Pagination
from app.utils.validation import plain_text


class TrackingLinkFilters(Pagination):
    article_id: UUID | None = None


class UtmParameters(Input):
    utm_source: str | None = Field(default=None, min_length=1, max_length=100)
    utm_medium: str | None = Field(default=None, min_length=1, max_length=100)
    utm_campaign: str | None = Field(default=None, min_length=1, max_length=150)
    utm_content: str | None = Field(default=None, min_length=1, max_length=150)

    @field_validator("utm_source", "utm_medium")
    @classmethod
    def normalize_utm(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = plain_text(value).lower()
        if not value:
            raise ValueError("UTM values cannot be empty")
        return value

    @field_validator("utm_campaign", "utm_content")
    @classmethod
    def text_utm(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = plain_text(value)
        if not value:
            raise ValueError("UTM values cannot be empty")
        return value

    @model_validator(mode="after")
    def utm_requires_source(self) -> "UtmParameters":
        if not self.utm_source and any((self.utm_medium, self.utm_campaign, self.utm_content)):
            raise ValueError("utm_source is required with UTM metadata")
        return self


class UtmLinkCreate(Input):
    article_id: UUID
    source_id: UUID
    medium: str = Field(default="social", min_length=1, max_length=100)
    campaign: str | None = Field(default=None, min_length=1, max_length=150)
    content: str | None = Field(default=None, min_length=1, max_length=150)

    @model_validator(mode="after")
    def normalize_metadata(self) -> "UtmLinkCreate":
        normalized = UtmParameters(
            utm_source="placeholder",
            utm_medium=self.medium,
            utm_campaign=self.campaign,
            utm_content=self.content,
        )
        self.medium = normalized.utm_medium or "social"
        self.campaign = normalized.utm_campaign
        self.content = normalized.utm_content
        return self


class UtmLinkResponse(Output):
    article_slug: str
    relative_url: str
    utm_source: str
    utm_medium: str
    utm_campaign: str | None
    utm_content: str | None


class TrackingLinkCreate(Input):
    article_id: UUID
    code: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    source_id: UUID | None = None
    source: str | None = Field(default=None, min_length=1, max_length=100)
    medium: str = Field(default="social", min_length=1, max_length=100)
    campaign: str | None = Field(default=None, max_length=150)
    content: str | None = Field(default=None, max_length=150)

    @field_validator("source", "medium")
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        return plain_text(value).lower() if value is not None else None

    @field_validator("campaign", "content")
    @classmethod
    def text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return plain_text(value) or None

    @model_validator(mode="after")
    def require_source(self) -> "TrackingLinkCreate":
        if self.source_id is None and self.source is None:
            raise ValueError("Select a traffic source")
        return self


class TrackingLinkUpdate(Input):
    is_active: bool


class TrackingLinkResponse(Output):
    id: UUID
    source_id: UUID
    article_id: UUID
    code: str
    source: str
    medium: str
    campaign: str | None
    content: str | None
    is_active: bool
    created_at: datetime


class TrackingDestination(TrackingLinkResponse):
    article_slug: str


class ArticleViewCreate(UtmParameters):
    event_id: UUID
    session_id: UUID
    article_slug: str = Field(min_length=1, max_length=350, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    tracking_link_id: UUID | None = None
    referrer_domain: str | None = Field(default=None, max_length=253)

    @model_validator(mode="after")
    def one_attribution(self) -> "ArticleViewCreate":
        if self.tracking_link_id and self.utm_source:
            raise ValueError("Send UTM attribution or tracking_link_id, not both")
        return self

    @field_validator("referrer_domain")
    @classmethod
    def domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        import re

        value = value.lower().rstrip(".")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value):
            raise ValueError("Expected a hostname")
        return value


class AnalyticsFilters(Input):
    start: datetime = Field(default_factory=lambda: datetime.now(UTC) - timedelta(days=30))
    end: datetime = Field(default_factory=lambda: datetime.now(UTC))
    article_id: UUID | None = None
    source: str | None = Field(default=None, max_length=100)
    campaign: str | None = Field(default=None, max_length=150)
    tracking_link_id: UUID | None = None
    group_by: Literal["source", "article", "campaign", "link", "day"] = "source"
    page: int = Field(default=1, ge=1, le=100000)
    page_size: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def range_valid(self) -> "AnalyticsFilters":
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("Use timezone-aware start/end with start before end")
        if self.end - self.start > timedelta(days=366):
            raise ValueError("Maximum report range is 366 days")
        return self


class AnalyticsRow(Output):
    key: str
    views: int
    sessions: int


class AnalyticsReport(Output):
    views: int
    sessions: int
    groups: list[AnalyticsRow]
    total_groups: int
    page: int
    page_size: int


class TrafficSourceCreate(Input):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    referrer_domains: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("name")
    @classmethod
    def plain_name(cls, value: str) -> str:
        return plain_text(value)

    @field_validator("referrer_domains")
    @classmethod
    def domains(cls, values: list[str]) -> list[str]:
        import re

        result = []
        for value in values:
            domain = value.strip().lower().rstrip(".")
            labels = domain.split(".")
            if (
                len(domain) > 253
                or len(labels) < 2
                or len(labels[-1]) < 2
                or labels[-1].isdigit()
                or any(
                    not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in labels
                )
            ):
                raise ValueError("Use hostnames such as linkedin.com without paths or protocols")
            result.append(domain)
        if len(result) != len(set(result)):
            raise ValueError("Referrer domains must be unique")
        return result


class TrafficSourceUpdate(Input):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    referrer_domains: list[str] | None = Field(default=None, max_length=20)
    is_active: bool | None = None

    @model_validator(mode="after")
    def valid_values(self) -> "TrafficSourceUpdate":
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError("Source fields cannot be null")
        if self.name is not None:
            self.name = plain_text(self.name)
        if self.referrer_domains is not None:
            self.referrer_domains = TrafficSourceCreate.domains(self.referrer_domains)
        return self


class TrafficSourceResponse(Output):
    id: UUID
    name: str
    slug: str
    referrer_domains: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SourceCounts(TrafficSourceResponse):
    views: int
    sessions: int


class TrafficOverviewFilters(Input):
    article_id: UUID | None = None
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def valid_range(self) -> "TrafficOverviewFilters":
        for value in (self.start, self.end):
            if value is not None and value.tzinfo is None:
                raise ValueError("Dates must include a timezone")
        if self.start and self.end and self.start >= self.end:
            raise ValueError("Start must be before end")
        return self


class TrafficOverview(Output):
    views: int
    sessions: int
    lifetime_views: int
    legacy_views: int
    sources: list[SourceCounts]
    unassigned_views: int
    unassigned_sessions: int
