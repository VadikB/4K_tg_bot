"""Protect assessment specs and validate case limits."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_assessment_spec_guards"
down_revision: str | None = "0003_role_version_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    checks = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_check_constraints("project_assessment_specs")
    }
    if "ck_spec_required_case_count" not in checks:
        op.create_check_constraint(
            "ck_spec_required_case_count", "project_assessment_specs", "required_case_count > 0"
        )
    if "ck_spec_daily_case_limit" not in checks:
        op.create_check_constraint(
            "ck_spec_daily_case_limit", "project_assessment_specs", "daily_case_limit = 1"
        )
    op.execute(
        """CREATE OR REPLACE FUNCTION prevent_published_assessment_spec_change()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND OLD.status IN ('published', 'retired') THEN
                RAISE EXCEPTION 'Published assessment specs are immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.status IN ('published', 'retired') AND (
                NEW.project_id IS DISTINCT FROM OLD.project_id OR
                NEW.version IS DISTINCT FROM OLD.version OR
                NEW.assessment_configuration_ref IS DISTINCT FROM
                    OLD.assessment_configuration_ref OR
                NEW.assessment_configuration_checksum IS DISTINCT FROM
                    OLD.assessment_configuration_checksum OR
                NEW.methodology_ref IS DISTINCT FROM OLD.methodology_ref OR
                NEW.required_case_count IS DISTINCT FROM OLD.required_case_count OR
                NEW.daily_case_limit IS DISTINCT FROM OLD.daily_case_limit OR
                NEW.timezone IS DISTINCT FROM OLD.timezone OR
                NEW.available_from IS DISTINCT FROM OLD.available_from OR
                NEW.available_until IS DISTINCT FROM OLD.available_until OR
                NEW.result_recipient_policy IS DISTINCT FROM OLD.result_recipient_policy OR
                NEW.snapshot_json IS DISTINCT FROM OLD.snapshot_json OR
                NEW.checksum IS DISTINCT FROM OLD.checksum OR
                NEW.published_at IS DISTINCT FROM OLD.published_at OR
                (OLD.status = 'published' AND NEW.status NOT IN ('published', 'retired')) OR
                (OLD.status = 'retired' AND NEW.status <> 'retired')
            ) THEN
                RAISE EXCEPTION 'Published assessment specs are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql"""
    )
    op.execute(
        """CREATE TRIGGER trg_assessment_spec_immutable
           BEFORE UPDATE OR DELETE ON project_assessment_specs
           FOR EACH ROW EXECUTE FUNCTION prevent_published_assessment_spec_change()"""
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_assessment_spec_immutable ON project_assessment_specs")
    op.execute("DROP FUNCTION IF EXISTS prevent_published_assessment_spec_change()")
    checks = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_check_constraints("project_assessment_specs")
    }
    if "ck_spec_daily_case_limit" in checks:
        op.drop_constraint("ck_spec_daily_case_limit", "project_assessment_specs", type_="check")
    if "ck_spec_required_case_count" in checks:
        op.drop_constraint(
            "ck_spec_required_case_count", "project_assessment_specs", type_="check"
        )
