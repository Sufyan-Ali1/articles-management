from sqlalchemy import DateTime
from sqlalchemy.dialects import postgresql

from app.db.base import Base
from app.models import Article, article_categories, article_tags
from app.repositories.queries import article_query
from app.schemas.common import PublicArticleFilters


def test_application_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "authors",
        "tracking_links",
        "traffic_sources",
        "article_view_events",
        "subscribers",
        "contact_messages",
        "refresh_sessions",
        "media_assets",
        "articles",
        "categories",
        "tags",
        "article_types",
        "article_categories",
        "article_tags",
        "admin_logs",
        "article_requests",
    }
    assert set(Base.metadata.tables["article_requests"].columns.keys()) == {
        "id",
        "topic",
        "description",
        "name",
        "email",
        "status",
        "admin_notes",
        "reviewed_by",
        "created_at",
        "updated_at",
    }
    assert set(c.name for c in article_categories.primary_key) == {"article_id", "category_id"}
    assert set(c.name for c in article_tags.primary_key) == {"article_id", "tag_id"}


def test_all_timestamps_are_timezone_aware() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone


def test_foreign_key_deletion_rules() -> None:
    for table in (article_categories, article_tags):
        for foreign_key in table.foreign_keys:
            assert foreign_key.ondelete == (
                "CASCADE" if foreign_key.parent.name == "article_id" else "RESTRICT"
            )
    assert next(iter(Article.__table__.c.author_id.foreign_keys)).ondelete == "RESTRICT"
    assert (
        next(iter(Base.metadata.tables["article_requests"].c.reviewed_by.foreign_keys)).ondelete
        == "SET NULL"
    )


def test_public_query_excludes_unpublished_and_large_fields() -> None:
    query = article_query(PublicArticleFilters(), public=True)
    compiled = query.compile(dialect=postgresql.dialect())
    assert "published" in compiled.params.values()
    selected = str(compiled).split("FROM")[0]
    assert "articles.content_html" not in selected
    assert "articles.schema" not in selected
    assert "password_hash" not in selected
