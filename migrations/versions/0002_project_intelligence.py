"""Persist inspection runs and normalized project intelligence."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_project_intelligence"
down_revision: Union[str, None] = "0001_storage_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("root_path", sa.String(length=2048), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("current_inspection_id", sa.String(length=36), nullable=True),
    )
    op.create_table(
        "inspection_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "project_files",
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("inspection_runs.id"), primary_key=True),
        sa.Column("relative_path", sa.String(length=2048), primary_key=True),
        sa.Column("classification", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("ignored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "project_components",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("inspection_runs.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=True),
        sa.Column("framework", sa.String(length=128), nullable=True),
        sa.Column("package_manager", sa.String(length=64), nullable=True),
    )
    for table_name, columns in {
        "project_dependencies": [
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("inspection_runs.id"), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("version", sa.String(length=255), nullable=True),
            sa.Column("scope", sa.String(length=64), nullable=True),
            sa.Column("source_file", sa.String(length=2048), nullable=False),
            sa.Column("confidence", sa.String(length=16), nullable=False),
        ],
        "project_runtimes": [
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("inspection_runs.id"), nullable=False),
            sa.Column("runtime", sa.String(length=128), nullable=False),
            sa.Column("version", sa.String(length=255), nullable=True),
            sa.Column("source_file", sa.String(length=2048), nullable=False),
            sa.Column("confidence", sa.String(length=16), nullable=False),
        ],
        "project_commands": [
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("inspection_runs.id"), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("command", sa.Text(), nullable=False),
            sa.Column("source_file", sa.String(length=2048), nullable=False),
            sa.Column("confidence", sa.String(length=16), nullable=False),
        ],
        "project_ports": [
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("inspection_runs.id"), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("port", sa.Integer(), nullable=False),
            sa.Column("source_file", sa.String(length=2048), nullable=False),
            sa.Column("confidence", sa.String(length=16), nullable=False),
        ],
        "project_evidence": [
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("inspection_runs.id"), nullable=False),
            sa.Column("source_file", sa.String(length=2048), nullable=False),
            sa.Column("evidence_type", sa.String(length=128), nullable=False),
            sa.Column("key", sa.String(length=255), nullable=False),
            sa.Column("value", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.String(length=16), nullable=False),
            sa.Column("line_number", sa.Integer(), nullable=True),
            sa.Column("extraction_method", sa.String(length=128), nullable=False),
        ],
    }.items():
        op.create_table(table_name, *columns)


def downgrade() -> None:
    for table_name in (
        "project_evidence", "project_ports", "project_commands", "project_runtimes",
        "project_dependencies", "project_components", "project_files", "inspection_runs", "projects",
    ):
        op.drop_table(table_name)
