"""Initial nine application tables.

Downgrade destroys application data; use only on disposable databases or after a verified backup.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_types",
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_types")),
        sa.UniqueConstraint("slug", name=op.f("uq_article_types_slug")),
    )
    op.create_table(
        "categories",
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name=op.f("ck_categories_not_own_parent")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name=op.f("fk_categories_parent_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("slug", name=op.f("uq_categories_slug")),
    )
    op.create_index(op.f("ix_categories_parent_id"), "categories", ["parent_id"], unique=False)
    op.create_table(
        "tags",
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("slug", name=op.f("uq_tags_slug")),
    )
    op.create_table(
        "users",
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=30), server_default="author", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("role IN ('admin','editor','author')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "admin_logs",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_admin_logs_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_logs")),
    )
    op.create_index(op.f("ix_admin_logs_created_at"), "admin_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_admin_logs_entity_type"), "admin_logs", ["entity_type"], unique=False)
    op.create_index(op.f("ix_admin_logs_entity_id"), "admin_logs", ["entity_id"], unique=False)
    op.create_index(op.f("ix_admin_logs_user_id"), "admin_logs", ["user_id"], unique=False)
    op.create_table(
        "article_requests",
        sa.Column("topic", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','accepted','rejected','completed')",
            name=op.f("ck_article_requests_status"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name=op.f("fk_article_requests_reviewed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_requests")),
    )
    op.create_index(
        op.f("ix_article_requests_reviewed_by"), "article_requests", ["reviewed_by"], unique=False
    )
    op.create_index(
        "ix_article_requests_status_created_at",
        "article_requests",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "articles",
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("slug", sa.String(length=350), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column("article_type_id", sa.Uuid(), nullable=True),
        sa.Column("featured_image", sa.Text(), nullable=True),
        sa.Column("featured_image_alt", sa.String(length=300), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="draft", nullable=False),
        sa.Column("meta_title", sa.String(length=300), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("view_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name=op.f("ck_articles_publication_time"),
        ),
        sa.CheckConstraint(
            "status IN ('draft','published','archived')", name=op.f("ck_articles_status")
        ),
        sa.CheckConstraint("view_count >= 0", name=op.f("ck_articles_view_count")),
        sa.ForeignKeyConstraint(
            ["article_type_id"],
            ["article_types.id"],
            name=op.f("fk_articles_article_type_id_article_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_articles_author_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_articles")),
        sa.UniqueConstraint("slug", name=op.f("uq_articles_slug")),
    )
    op.create_index(
        op.f("ix_articles_article_type_id"), "articles", ["article_type_id"], unique=False
    )
    op.create_index(op.f("ix_articles_author_id"), "articles", ["author_id"], unique=False)
    op.create_index(
        "ix_articles_featured_published",
        "articles",
        ["published_at"],
        unique=False,
        postgresql_where=sa.text("is_featured AND status = 'published'"),
    )
    op.create_index(
        "ix_articles_status_published_at", "articles", ["status", "published_at"], unique=False
    )
    op.create_table(
        "article_categories",
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_article_categories_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_article_categories_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("article_id", "category_id", name=op.f("pk_article_categories")),
    )
    op.create_index(
        "ix_article_categories_category_id", "article_categories", ["category_id"], unique=False
    )
    op.create_table(
        "article_tags",
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_article_tags_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_article_tags_tag_id_tags"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("article_id", "tag_id", name=op.f("pk_article_tags")),
    )
    op.create_index("ix_article_tags_tag_id", "article_tags", ["tag_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_article_tags_tag_id", table_name="article_tags")
    op.drop_table("article_tags")
    op.drop_index("ix_article_categories_category_id", table_name="article_categories")
    op.drop_table("article_categories")
    op.drop_index("ix_articles_status_published_at", table_name="articles")
    op.drop_index(
        "ix_articles_featured_published",
        table_name="articles",
        postgresql_where=sa.text("is_featured AND status = 'published'"),
    )
    op.drop_index(op.f("ix_articles_author_id"), table_name="articles")
    op.drop_index(op.f("ix_articles_article_type_id"), table_name="articles")
    op.drop_table("articles")
    op.drop_index("ix_article_requests_status_created_at", table_name="article_requests")
    op.drop_index(op.f("ix_article_requests_reviewed_by"), table_name="article_requests")
    op.drop_table("article_requests")
    op.drop_index(op.f("ix_admin_logs_user_id"), table_name="admin_logs")
    op.drop_index(op.f("ix_admin_logs_entity_id"), table_name="admin_logs")
    op.drop_index(op.f("ix_admin_logs_entity_type"), table_name="admin_logs")
    op.drop_index(op.f("ix_admin_logs_created_at"), table_name="admin_logs")
    op.drop_table("admin_logs")
    op.drop_table("users")
    op.drop_table("tags")
    op.drop_index(op.f("ix_categories_parent_id"), table_name="categories")
    op.drop_table("categories")
    op.drop_table("article_types")
