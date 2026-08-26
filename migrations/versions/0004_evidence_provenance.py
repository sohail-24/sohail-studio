"""Persist explicit and deterministic evidence provenance."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_evidence_provenance"
down_revision: Union[str, None] = "0003_project_intel_refine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("project_evidence")}
    if "source_type" not in columns:
        op.add_column(
            "project_evidence",
            sa.Column("source_type", sa.String(length=64), nullable=False, server_default="EXPLICIT_EVIDENCE"),
        )
    if "derived_from" not in columns:
        op.add_column(
            "project_evidence",
            sa.Column("derived_from", sa.JSON(), nullable=False, server_default="[]"),
        )
    if "rule_id" not in columns:
        op.add_column("project_evidence", sa.Column("rule_id", sa.String(length=128), nullable=True))
    if "model_inference" not in columns:
        op.add_column(
            "project_evidence",
            sa.Column("model_inference", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("project_evidence")}
    for column in ("model_inference", "rule_id", "derived_from", "source_type"):
        if column in columns:
            op.drop_column("project_evidence", column)
