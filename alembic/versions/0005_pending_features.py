"""Pending publishing, subscription, contact and traffic tracking features.

Consolidates the unapplied changes after 0004. Do not apply until ready.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_pending_features"
down_revision = "0004_media_deletion_pending"
branch_labels = None
depends_on = None


def upgrade_schedule() -> None:
    op.add_column("articles", sa.Column("scheduled_publish_at", sa.DateTime(timezone=True)))
    op.drop_constraint(op.f("ck_articles_status"), "articles", type_="check")
    op.create_check_constraint(
        op.f("ck_articles_status"),
        "articles",
        "status IN ('draft','published','archived','scheduled')",
    )
    op.create_check_constraint(
        op.f("ck_articles_schedule_time"),
        "articles",
        "(status = 'scheduled') = (scheduled_publish_at IS NOT NULL)",
    )
    op.create_index(
        "ix_articles_status_scheduled_publish_at", "articles", ["status", "scheduled_publish_at"]
    )


def downgrade_schedule() -> None:
    op.execute(
        "UPDATE articles SET status = 'draft', scheduled_publish_at = NULL WHERE status = 'scheduled'"
    )
    op.drop_index("ix_articles_status_scheduled_publish_at", table_name="articles")
    op.drop_constraint(op.f("ck_articles_schedule_time"), "articles", type_="check")
    op.drop_constraint(op.f("ck_articles_status"), "articles", type_="check")
    op.create_check_constraint(
        op.f("ck_articles_status"), "articles", "status IN ('draft','published','archived')"
    )
    op.drop_column("articles", "scheduled_publish_at")


def upgrade_subscribers() -> None:
    op.create_table(
        "subscribers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_subscribers_created_at", "subscribers", ["created_at"])


def downgrade_subscribers() -> None:
    op.drop_index("ix_subscribers_created_at", table_name="subscribers")
    op.drop_table("subscribers")


def upgrade_contacts() -> None:
    op.create_table(
        "contact_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(150), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("article_url", sa.String(2048), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "reason IN ('general','correction','privacy')", name=op.f("ck_contact_messages_reason")
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contact_messages_created_at", "contact_messages", ["created_at"])


def downgrade_contacts() -> None:
    op.drop_index("ix_contact_messages_created_at", table_name="contact_messages")
    op.drop_table("contact_messages")


def upgrade_analytics() -> None:
    op.create_table(
        "traffic_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column(
            "referrer_domains",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "tracking_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("medium", sa.String(100), nullable=False),
        sa.Column("campaign", sa.String(150), nullable=True),
        sa.Column("content", sa.String(150), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["traffic_sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_tracking_links_source_id", "tracking_links", ["source_id"])
    op.create_index("ix_tracking_links_article_id", "tracking_links", ["article_id"])
    op.create_table(
        "article_view_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=False),
        sa.Column("tracking_link_id", sa.UUID(), nullable=True),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(253), nullable=False),
        sa.Column("medium", sa.String(100), nullable=False),
        sa.Column("campaign", sa.String(150), nullable=True),
        sa.Column("content", sa.String(150), nullable=True),
        sa.Column("referrer_domain", sa.String(253), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["traffic_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tracking_link_id"], ["tracking_links.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    for name, columns in (
        ("ix_article_view_events_source_id", ["source_id"]),
        ("ix_article_view_events_session_id", ["session_id"]),
        ("ix_article_view_events_tracking_link_id", ["tracking_link_id"]),
        ("ix_article_view_events_created_at", ["created_at"]),
        ("ix_article_view_events_article_created", ["article_id", "created_at"]),
        ("ix_article_view_events_source_created", ["source", "created_at"]),
    ):
        op.create_index(name, "article_view_events", columns)


def downgrade_analytics() -> None:
    op.drop_table("article_view_events")
    op.drop_table("tracking_links")
    op.drop_table("traffic_sources")


def upgrade() -> None:
    upgrade_schedule()
    upgrade_subscribers()
    upgrade_contacts()
    upgrade_analytics()


def downgrade() -> None:
    downgrade_analytics()
    downgrade_contacts()
    downgrade_subscribers()
    downgrade_schedule()
