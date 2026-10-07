"""question options (MCQ papers)

Revision ID: c8d2e4f6a1b3
Revises: b7c1d2e3f4a5
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "c8d2e4f6a1b3"
down_revision = "b7c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.add_column(sa.Column("options", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.drop_column("options")
