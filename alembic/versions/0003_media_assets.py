"""Track uploaded images and deferred cleanup."""

import sqlalchemy as sa

from alembic import op

revision = "0003_media_assets"
down_revision = "0002_refresh_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("public_id", sa.String(255), nullable=False),
        sa.Column("secure_url", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("unused_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("secure_url"),
    )
    op.create_index("ix_media_assets_unused_since", "media_assets", ["unused_since"])


def downgrade() -> None:
    op.drop_table("media_assets")
