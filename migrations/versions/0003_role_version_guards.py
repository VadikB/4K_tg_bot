"""Protect published project roles and enforce one primary role."""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_role_version_guards"
down_revision: str | None = "0002_pending_participants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_participant_primary_role
           ON project_participant_roles(participant_id) WHERE is_primary"""
    )
    op.execute(
        """CREATE OR REPLACE FUNCTION prevent_published_project_role_change()
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
    op.execute(
        """DROP TRIGGER IF EXISTS trg_project_role_version_immutable
           ON project_role_versions"""
    )
    op.execute(
        """CREATE TRIGGER trg_project_role_version_immutable
           BEFORE UPDATE OR DELETE ON project_role_versions
           FOR EACH ROW EXECUTE FUNCTION prevent_published_project_role_change()"""
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_project_role_version_immutable ON project_role_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_published_project_role_change()")
    op.execute("DROP INDEX IF EXISTS uq_participant_primary_role")
