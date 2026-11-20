"""Keep the intended Telegram user ID for new participant invitations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_invited_telegram_user_id"
down_revision: str | None = "0010_role_profile_bindings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("project_participants")}
    if "invited_telegram_user_id" not in columns:
        op.add_column(
            "project_participants",
            sa.Column("invited_telegram_user_id", sa.BigInteger(), nullable=True),
        )
    inspector = sa.inspect(bind)
    constraints = {
        item["name"] for item in inspector.get_unique_constraints("project_participants")
    }
    if "uq_project_participant_invited_tg_id" not in constraints:
        op.create_unique_constraint(
            "uq_project_participant_invited_tg_id",
            "project_participants",
            ["project_id", "invited_telegram_user_id"],
        )
    checks = {item["name"] for item in inspector.get_check_constraints("project_participants")}
    if "ck_project_participant_invited_tg_id" not in checks:
        op.create_check_constraint(
            "ck_project_participant_invited_tg_id",
            "project_participants",
            "invited_telegram_user_id IS NULL OR invited_telegram_user_id > 0",
        )


def downgrade() -> None:
    bind = op.get_bind()
    linked = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM project_participants "
            "WHERE invited_telegram_user_id IS NOT NULL"
        )
    ).scalar_one()
    if linked:
        raise RuntimeError("Cannot downgrade while Telegram ID invitations exist")
    op.drop_constraint(
        "ck_project_participant_invited_tg_id", "project_participants", type_="check"
    )
    op.drop_constraint(
        "uq_project_participant_invited_tg_id", "project_participants", type_="unique"
    )
    op.drop_column("project_participants", "invited_telegram_user_id")
