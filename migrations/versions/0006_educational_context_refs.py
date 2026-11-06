"""Add stable course and Agent4K role-profile references."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_educational_context_refs"
down_revision: str | None = "0005_participant_email_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_role_guard(*, include_agent4k_refs: bool) -> None:
    mapping_guard = """
                NEW.agent4k_role_profile_version_id IS DISTINCT FROM
                    OLD.agent4k_role_profile_version_id OR
                NEW.agent4k_role_profile_checksum IS DISTINCT FROM
                    OLD.agent4k_role_profile_checksum OR
    """ if include_agent4k_refs else ""
    op.execute(
        f"""CREATE OR REPLACE FUNCTION prevent_published_project_role_change()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND OLD.status IN ('published', 'retired') THEN
                RAISE EXCEPTION 'Published project role versions are immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.status IN ('published', 'retired') AND (
                NEW.project_role_id IS DISTINCT FROM OLD.project_role_id OR
                NEW.version IS DISTINCT FROM OLD.version OR
                NEW.definition_json IS DISTINCT FROM OLD.definition_json OR
                NEW.source_json IS DISTINCT FROM OLD.source_json OR
                {mapping_guard}
                NEW.checksum IS DISTINCT FROM OLD.checksum OR
                NEW.published_at IS DISTINCT FROM OLD.published_at OR
                (OLD.status = 'published' AND NEW.status NOT IN ('published', 'retired')) OR
                (OLD.status = 'retired' AND NEW.status <> 'retired')
            ) THEN
                RAISE EXCEPTION 'Published project role versions are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql"""
    )


def upgrade() -> None:
    bind = op.get_bind()
    project_columns = {item["name"] for item in sa.inspect(bind).get_columns("projects")}
    if "course_external_id" not in project_columns:
        op.add_column("projects", sa.Column("course_external_id", sa.String(128)))
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_projects_course_external_id "
        "ON projects(course_external_id)"
    )

    role_columns = {
        item["name"] for item in sa.inspect(bind).get_columns("project_role_versions")
    }
    if "agent4k_role_profile_version_id" not in role_columns:
        op.add_column(
            "project_role_versions",
            sa.Column("agent4k_role_profile_version_id", sa.BigInteger()),
        )
    if "agent4k_role_profile_checksum" not in role_columns:
        op.add_column(
            "project_role_versions",
            sa.Column("agent4k_role_profile_checksum", sa.String(64)),
        )
    checks = {
        item["name"]
        for item in sa.inspect(bind).get_check_constraints("project_role_versions")
    }
    if "ck_project_role_agent4k_mapping" not in checks:
        op.create_check_constraint(
            "ck_project_role_agent4k_mapping",
            "project_role_versions",
            "(agent4k_role_profile_version_id IS NULL AND "
            "agent4k_role_profile_checksum IS NULL) OR "
            "(agent4k_role_profile_version_id > 0 AND "
            "agent4k_role_profile_checksum ~ '^[0-9a-f]{64}$')",
        )
    _install_role_guard(include_agent4k_refs=True)


def downgrade() -> None:
    _install_role_guard(include_agent4k_refs=False)
    checks = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_check_constraints("project_role_versions")
    }
    if "ck_project_role_agent4k_mapping" in checks:
        op.drop_constraint(
            "ck_project_role_agent4k_mapping", "project_role_versions", type_="check"
        )
    role_columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("project_role_versions")
    }
    for column in ("agent4k_role_profile_checksum", "agent4k_role_profile_version_id"):
        if column in role_columns:
            op.drop_column("project_role_versions", column)
    op.execute("DROP INDEX IF EXISTS ix_projects_course_external_id")
    project_columns = {
        item["name"] for item in sa.inspect(op.get_bind()).get_columns("projects")
    }
    if "course_external_id" in project_columns:
        op.drop_column("projects", "course_external_id")
