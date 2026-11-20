"""Add immutable educational assessment context snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_context_snapshots"
down_revision: str | None = "0006_educational_context_refs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "project_assessment_context_snapshots" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "project_assessment_context_snapshots",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column(
                "assessment_assignment_id",
                sa.BigInteger(),
                sa.ForeignKey("assessment_assignments.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("assignment_ref", sa.String(200), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
            sa.Column("checksum", sa.String(64), nullable=False),
            sa.Column(
                "published_by_user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "published_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "assessment_assignment_id", name="uq_context_snapshot_assignment"
            ),
            sa.UniqueConstraint("assignment_ref"),
            sa.CheckConstraint("status = 'published'", name="ck_context_snapshot_status"),
        )
    op.execute(
        """CREATE OR REPLACE FUNCTION prevent_assessment_context_snapshot_change()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Published assessment context snapshots are immutable';
        END;
        $$ LANGUAGE plpgsql"""
    )
    op.execute(
        """DROP TRIGGER IF EXISTS assessment_context_snapshot_immutable
        ON project_assessment_context_snapshots"""
    )
    op.execute(
        """CREATE TRIGGER assessment_context_snapshot_immutable
        BEFORE UPDATE OR DELETE ON project_assessment_context_snapshots
        FOR EACH ROW EXECUTE FUNCTION prevent_assessment_context_snapshot_change()"""
    )


def downgrade() -> None:
    op.execute(
        """DROP TRIGGER IF EXISTS assessment_context_snapshot_immutable
        ON project_assessment_context_snapshots"""
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_assessment_context_snapshot_change()")
    op.drop_table("project_assessment_context_snapshots")
