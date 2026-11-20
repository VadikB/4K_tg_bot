"""Add participant email and nullable Agent4K identity link."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_participant_email_link"
down_revision: str | None = "0004_assessment_spec_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("project_participants")}
    if "email" not in columns:
        op.add_column("project_participants", sa.Column("email", sa.String(320)))
    if "agent4k_user_id" not in columns:
        op.add_column("project_participants", sa.Column("agent4k_user_id", sa.BigInteger()))
    if "agent4k_linked_at" not in columns:
        op.add_column(
            "project_participants",
            sa.Column("agent4k_linked_at", sa.DateTime(timezone=True)),
        )

    inspector = sa.inspect(bind)
    unique_constraints = {
        item["name"] for item in inspector.get_unique_constraints("project_participants")
    }
    if "uq_project_participant_email" not in unique_constraints:
        op.create_unique_constraint(
            "uq_project_participant_email", "project_participants", ["project_id", "email"]
        )
    checks = {
        item["name"] for item in inspector.get_check_constraints("project_participants")
    }
    if "ck_project_participant_agent4k_link" not in checks:
        op.create_check_constraint(
            "ck_project_participant_agent4k_link",
            "project_participants",
            "agent4k_user_id IS NOT NULL OR agent4k_linked_at IS NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    checks = {
        item["name"]
        for item in sa.inspect(bind).get_check_constraints("project_participants")
    }
    if "ck_project_participant_agent4k_link" in checks:
        op.drop_constraint(
            "ck_project_participant_agent4k_link", "project_participants", type_="check"
        )
    unique_constraints = {
        item["name"]
        for item in sa.inspect(bind).get_unique_constraints("project_participants")
    }
    if "uq_project_participant_email" in unique_constraints:
        op.drop_constraint(
            "uq_project_participant_email", "project_participants", type_="unique"
        )
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("project_participants")
    }
    for column in ("agent4k_linked_at", "agent4k_user_id", "email"):
        if column in columns:
            op.drop_column("project_participants", column)
