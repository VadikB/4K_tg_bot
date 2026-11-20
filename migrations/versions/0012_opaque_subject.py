"""Opaque external assessment reference; no contact data copied to 4K."""

import sqlalchemy as sa
from alembic import op

revision = "0012_opaque_subject"
down_revision = "0011_invited_telegram_user_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("assessment_context_preparations", "external_assignment_id", nullable=True)
    inspector = sa.inspect(op.get_bind())
    if "external_subject_ref" not in {
        x["name"] for x in inspector.get_columns("project_participants")
    }:
        op.add_column(
            "project_participants", sa.Column("external_subject_ref", sa.String(36), nullable=True)
        )
    inspector = sa.inspect(op.get_bind())
    if "uq_participant_external_subject" not in {
        x["name"] for x in inspector.get_unique_constraints("project_participants")
    }:
        op.create_unique_constraint(
            "uq_participant_external_subject", "project_participants", ["external_subject_ref"]
        )
    op.drop_constraint("ck_project_participant_agent4k_link", "project_participants", type_="check")
    op.create_check_constraint(
        "ck_project_participant_agent4k_link",
        "project_participants",
        "agent4k_user_id IS NOT NULL OR external_subject_ref IS NOT NULL "
        "OR agent4k_linked_at IS NULL",
    )


def downgrade() -> None:
    pending = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM assessment_context_preparations "
                "WHERE external_assignment_id IS NULL LIMIT 1"
            )
        )
        .first()
    )
    if pending:
        raise RuntimeError("Keep pending preparation metadata during code rollback")
    linked = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM project_participants WHERE external_subject_ref IS NOT NULL LIMIT 1"
            )
        )
        .first()
    )
    if linked:
        raise RuntimeError("Keep the additive column during code rollback: subject bindings exist")
    op.drop_constraint("ck_project_participant_agent4k_link", "project_participants", type_="check")
    op.create_check_constraint(
        "ck_project_participant_agent4k_link",
        "project_participants",
        "agent4k_user_id IS NOT NULL OR agent4k_linked_at IS NULL",
    )
    op.drop_constraint("uq_participant_external_subject", "project_participants", type_="unique")
    op.drop_column("project_participants", "external_subject_ref")
    op.alter_column("assessment_context_preparations", "external_assignment_id", nullable=False)
