"""Separate public author profiles from article creator accounts.

Prepared only; do not apply until deployment is authorized.
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_author_profiles"
down_revision = "0005_pending_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("specialization", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_authors")),
    )
    op.drop_constraint(op.f("fk_articles_author_id_users"), "articles", type_="foreignkey")
    op.drop_index("ix_articles_author_id", table_name="articles")
    op.alter_column("articles", "author_id", new_column_name="created_by_id")
    op.create_foreign_key(
        op.f("fk_articles_created_by_id_users"),
        "articles",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_articles_created_by_id", "articles", ["created_by_id"])
    op.add_column("articles", sa.Column("author_id", sa.UUID(), nullable=True))
    # Preserve existing bylines without changing creator ownership or article status.
    op.execute("""
        INSERT INTO authors (id, name, specialization, is_active)
        SELECT DISTINCT u.id, u.name, 'General', u.is_active
        FROM users u JOIN articles a ON a.created_by_id = u.id
    """)
    op.execute("UPDATE articles SET author_id = created_by_id WHERE created_by_id IS NOT NULL")
    op.create_foreign_key(
        op.f("fk_articles_author_id_authors"),
        "articles",
        "authors",
        ["author_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_articles_author_id", "articles", ["author_id"])


def downgrade() -> None:
    op.drop_index("ix_articles_author_id", table_name="articles")
    op.drop_constraint(op.f("fk_articles_author_id_authors"), "articles", type_="foreignkey")
    op.drop_column("articles", "author_id")
    op.drop_index("ix_articles_created_by_id", table_name="articles")
    op.drop_constraint(op.f("fk_articles_created_by_id_users"), "articles", type_="foreignkey")
    op.alter_column("articles", "created_by_id", new_column_name="author_id")
    op.create_foreign_key(
        op.f("fk_articles_author_id_users"),
        "articles",
        "users",
        ["author_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_articles_author_id", "articles", ["author_id"])
    op.drop_table("authors")
