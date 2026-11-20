"""Add mutable Agent4K context preparation state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_context_preparations"
down_revision: str | None = "0007_context_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "assessment_context_preparations" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "assessment_context_preparations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "context_snapshot_id",
            sa.BigInteger(),
            sa.ForeignKey("project_assessment_context_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("external_operation_id", sa.String(255), nullable=False, unique=True),
        sa.Column("external_organization_id", sa.BigInteger(), nullable=False),
        sa.Column("external_assignment_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "reasons_json", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("external_cycle_id", sa.String(255)),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("assessment_context_preparations")
