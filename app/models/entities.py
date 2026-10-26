from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps


class User(Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin','editor','author')", name="role"),)
    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), server_default="author")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    password_fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Classification(Timestamps):
    name: Mapped[str] = mapped_column(String(150))
    slug: Mapped[str] = mapped_column(String(180), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Category(Classification, Base):
    __tablename__ = "categories"
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    __table_args__ = (
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
    )


class Tag(Classification, Base):
    __tablename__ = "tags"


class ArticleType(Classification, Base):
    __tablename__ = "article_types"


article_categories = Table(
    "article_categories",
    Base.metadata,
    Column("article_id", ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "category_id",
        ForeignKey("categories.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Index("ix_article_categories_category_id", "category_id"),
)
article_tags = Table(
    "article_tags",
    Base.metadata,
    Column("article_id", ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="RESTRICT"), primary_key=True),
    Index("ix_article_tags_tag_id", "tag_id"),
)


class Article(Timestamps, Base):
    __tablename__ = "articles"
    __table_args__ = (
        CheckConstraint("status IN ('draft','published','archived','scheduled')", name="status"),
        CheckConstraint("view_count >= 0", name="view_count"),
        CheckConstraint(
            "(status = 'scheduled') = (scheduled_publish_at IS NOT NULL)",
            name="schedule_time",
        ),
        Index("ix_articles_status_scheduled_publish_at", "status", "scheduled_publish_at"),
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL", name="publication_time"
        ),
        Index("ix_articles_status_published_at", "status", "published_at"),
        Index(
            "ix_articles_featured_published",
            "published_at",
            postgresql_where=text("is_featured AND status = 'published'"),
        ),
    )
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(350), unique=True)
    excerpt: Mapped[str | None] = mapped_column(Text)
    content_html: Mapped[str] = mapped_column(Text)
    article_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("article_types.id", ondelete="RESTRICT"), index=True
    )
    featured_image: Mapped[str | None] = mapped_column(Text)
    featured_image_alt: Mapped[str | None] = mapped_column(String(300))
    author_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), server_default="draft")
    meta_title: Mapped[str | None] = mapped_column(String(300))
    meta_description: Mapped[str | None] = mapped_column(Text)
    schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_featured: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    view_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    categories: Mapped[list[Category]] = relationship(secondary=article_categories, lazy="raise")
    tags: Mapped[list[Tag]] = relationship(secondary=article_tags, lazy="raise")
    article_type: Mapped[ArticleType | None] = relationship(lazy="raise")
    author: Mapped[User | None] = relationship(lazy="raise")


class AdminLog(Base):
    __tablename__ = "admin_logs"
    __table_args__ = (Index("ix_admin_logs_entity_id", "entity_id"),)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_id: Mapped[UUID | None]
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ArticleRequest(Timestamps, Base):
    __tablename__ = "article_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','rejected','completed')", name="status"),
        Index("ix_article_requests_status_created_at", "status", "created_at"),
    )
    topic: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), server_default="pending")
    admin_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class MediaAsset(Base):
    __tablename__ = "media_assets"
    public_id: Mapped[str] = mapped_column(String(255), unique=True)
    secure_url: Mapped[str | None] = mapped_column(Text, unique=True)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    unused_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deletion_pending: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    deleted: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class Subscriber(Base):
    __tablename__ = "subscribers"
    email: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ContactMessage(Base):
    __tablename__ = "contact_messages"
    __table_args__ = (
        CheckConstraint("reason IN ('general','correction','privacy')", name="reason"),
    )
    name: Mapped[str | None] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(String(30))
    article_url: Mapped[str | None] = mapped_column(String(2048))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class TrackingLink(Base):
    __tablename__ = "tracking_links"
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("traffic_sources.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(80), unique=True)
    source: Mapped[str] = mapped_column(String(100))
    medium: Mapped[str] = mapped_column(String(100))
    campaign: Mapped[str | None] = mapped_column(String(150))
    content: Mapped[str | None] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArticleViewEvent(Base):
    __tablename__ = "article_view_events"
    __table_args__ = (
        Index("ix_article_view_events_article_created", "article_id", "created_at"),
        Index("ix_article_view_events_source_created", "source", "created_at"),
    )
    event_id: Mapped[UUID] = mapped_column(unique=True)
    session_id: Mapped[UUID] = mapped_column(index=True)
    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    tracking_link_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tracking_links.id", ondelete="SET NULL"), index=True
    )
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("traffic_sources.id", ondelete="RESTRICT"), index=True
    )
    source: Mapped[str] = mapped_column(String(253))
    medium: Mapped[str] = mapped_column(String(100))
    campaign: Mapped[str | None] = mapped_column(String(150))
    content: Mapped[str | None] = mapped_column(String(150))
    referrer_domain: Mapped[str | None] = mapped_column(String(253))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class TrafficSource(Timestamps, Base):
    __tablename__ = "traffic_sources"
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    referrer_domains: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
