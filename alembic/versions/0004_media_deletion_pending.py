"""Add the media deletion retry marker required by the asset model."""

import sqlalchemy as sa

from alembic import op

revision = "0004_media_deletion_pending"
down_revision = "0003_media_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_assets",
        sa.Column("deletion_pending", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("media_assets", "deletion_pending")
