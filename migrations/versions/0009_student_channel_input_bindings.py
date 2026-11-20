"""Add technical Telegram text-action bindings without answer content."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_channel_input_bindings"
down_revision: str | None = "0008_context_preparations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "student_channel_input_bindings" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "student_channel_input_bindings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id", sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "assessment_assignment_id", sa.BigInteger(),
            sa.ForeignKey("assessment_assignments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("assignment_ref", sa.String(200), nullable=False),
        sa.Column("action_id", sa.String(255), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("input_kind", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("payload_checksum", sa.String(64)),
        sa.Column("telegram_chat_id", sa.BigInteger()),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("response_revision", sa.Integer()),
        sa.Column("attempt_started_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'completed', 'stale')",
            name="ck_student_channel_binding_status",
        ),
        sa.CheckConstraint("input_kind = 'text'", name="ck_student_channel_input_kind"),
    )
    op.create_index(
        "uq_student_channel_pending_user",
        "student_channel_input_bindings",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'sending')"),
    )


def downgrade() -> None:
    op.drop_table("student_channel_input_bindings")
