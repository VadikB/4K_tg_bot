"""Allow new project settings to leave the 4K owned case count unset."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_optional_case_count"
down_revision: str | None = "0012_opaque_subject"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "project_assessment_specs", "required_case_count",
        existing_type=sa.Integer(), nullable=True,
    )


def downgrade() -> None:
    count = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM project_assessment_specs WHERE required_case_count IS NULL"
    )).scalar_one()
    if count:
        raise RuntimeError(
            "Cannot restore NOT NULL while 4K owned case count specs exist; retain the new schema."
        )
    op.alter_column(
        "project_assessment_specs", "required_case_count",
        existing_type=sa.Integer(), nullable=False,
    )
