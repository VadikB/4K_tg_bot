"""Pin a verified 4K RoleProfileVersion without changing published student roles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_role_profile_bindings"
down_revision: str | None = "0009_channel_input_bindings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "role_profile_bindings" not in inspector.get_table_names():
        op.create_table(
            "role_profile_bindings",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column(
                "project_role_version_id", sa.BigInteger(),
                sa.ForeignKey("project_role_versions.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("agent4k_role_profile_version_id", sa.BigInteger(), nullable=False),
            sa.Column("agent4k_role_profile_checksum", sa.String(64), nullable=False),
            sa.Column(
                "published_by_user_id", sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
            ),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "project_role_version_id", "version",
                name="uq_role_profile_binding_version",
            ),
            sa.CheckConstraint("version > 0", name="ck_role_profile_binding_version"),
            sa.CheckConstraint(
                "agent4k_role_profile_version_id > 0", name="ck_role_profile_binding_id"
            ),
            sa.CheckConstraint(
                "agent4k_role_profile_checksum ~ '^[0-9a-f]{64}$'",
                name="ck_role_profile_binding_checksum",
            ),
        )
    columns = {column["name"] for column in inspector.get_columns("assessment_assignments")}
    if "role_profile_binding_id" not in columns:
        op.add_column(
            "assessment_assignments",
            sa.Column("role_profile_binding_id", sa.BigInteger(), nullable=True),
        )
        op.create_foreign_key(
            "fk_assignment_role_profile_binding",
            "assessment_assignments",
            "role_profile_bindings",
            ["role_profile_binding_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.execute(
        """CREATE OR REPLACE FUNCTION prevent_role_profile_binding_change()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Published role profile bindings are immutable';
        END;
        $$ LANGUAGE plpgsql"""
    )
    op.execute(
        """DROP TRIGGER IF EXISTS trg_role_profile_binding_immutable
           ON role_profile_bindings"""
    )
    op.execute(
        """CREATE TRIGGER trg_role_profile_binding_immutable
           BEFORE UPDATE OR DELETE ON role_profile_bindings
           FOR EACH ROW EXECUTE FUNCTION prevent_role_profile_binding_change()"""
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION prevent_assignment_role_binding_change()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.role_profile_binding_id IS DISTINCT FROM OLD.role_profile_binding_id THEN
                RAISE EXCEPTION 'Assessment role profile binding is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql"""
    )
    op.execute(
        """DROP TRIGGER IF EXISTS trg_assignment_role_binding_immutable
           ON assessment_assignments"""
    )
    op.execute(
        """CREATE TRIGGER trg_assignment_role_binding_immutable
           BEFORE UPDATE ON assessment_assignments
           FOR EACH ROW EXECUTE FUNCTION prevent_assignment_role_binding_change()"""
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS(SELECT 1 FROM role_profile_bindings)")).scalar_one():
        raise RuntimeError("Cannot downgrade with published role profile bindings")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_assignment_role_binding_immutable ON assessment_assignments"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_assignment_role_binding_change()")
    op.execute("DROP TRIGGER IF EXISTS trg_role_profile_binding_immutable ON role_profile_bindings")
    op.execute("DROP FUNCTION IF EXISTS prevent_role_profile_binding_change()")
    op.drop_column("assessment_assignments", "role_profile_binding_id")
    op.drop_table("role_profile_bindings")
