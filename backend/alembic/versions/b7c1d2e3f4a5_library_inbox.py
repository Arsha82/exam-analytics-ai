"""library inbox: sources without a course yet

Revision ID: b7c1d2e3f4a5
Revises: 27422f083d73
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op

revision = "b7c1d2e3f4a5"
down_revision = "27422f083d73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("source_documents", "source_candidates"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("course_code", existing_type=sa.String(32), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM source_documents WHERE course_code IS NULL")
    op.execute("DELETE FROM source_candidates WHERE course_code IS NULL")
    for table in ("source_documents", "source_candidates"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("course_code", existing_type=sa.String(32), nullable=False)
