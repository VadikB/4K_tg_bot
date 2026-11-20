"""Allow a project participant to exist before Telegram registration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_pending_participants"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]: column
        for column in sa.inspect(bind).get_columns("project_participants")
    }
    if "display_name" not in columns:
        op.add_column("project_participants", sa.Column("display_name", sa.String(255)))
        op.execute(
            """UPDATE project_participants participant
               SET display_name = users.display_name
              FROM users WHERE users.id = participant.user_id"""
        )
        op.alter_column("project_participants", "display_name", nullable=False)
    if not columns["user_id"]["nullable"]:
        op.alter_column("project_participants", "user_id", nullable=True)
    checks = {
        item["name"] for item in sa.inspect(bind).get_check_constraints("project_participants")
    }
    if "ck_project_participant_identity" not in checks:
        op.create_check_constraint(
            "ck_project_participant_identity",
            "project_participants",
            "user_id IS NOT NULL OR status = 'invited'",
        )


def downgrade() -> None:
    bind = op.get_bind()
    pending = bind.execute(
        sa.text("SELECT COUNT(*) FROM project_participants WHERE user_id IS NULL")
    ).scalar_one()
    if pending:
        raise RuntimeError("Cannot downgrade while unclaimed participant invitations exist")
    checks = {
        item["name"] for item in sa.inspect(bind).get_check_constraints("project_participants")
    }
    if "ck_project_participant_identity" in checks:
        op.drop_constraint(
            "ck_project_participant_identity", "project_participants", type_="check"
        )
    op.alter_column("project_participants", "user_id", nullable=False)
    op.drop_column("project_participants", "display_name")
