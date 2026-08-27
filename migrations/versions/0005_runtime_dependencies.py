"""Add runtime dependencies table."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_runtime_dependencies"
down_revision: Union[str, None] = "0004_evidence_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_runtime_dependencies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("component", sa.String(length=255), nullable=False),
        sa.Column("dependency", sa.String(length=255), nullable=False),
        sa.Column("source_file", sa.String(length=2048), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["inspection_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("project_runtime_dependencies")
