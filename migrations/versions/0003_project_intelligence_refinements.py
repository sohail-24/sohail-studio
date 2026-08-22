"""Add component-aware port provenance for Phase 4B."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_project_intel_refine"
down_revision: Union[str, None] = "0002_project_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    component_columns = {column["name"] for column in inspector.get_columns("project_components")}
    port_columns = {column["name"] for column in inspector.get_columns("project_ports")}

    if "role" not in component_columns:
        op.add_column("project_components", sa.Column("role", sa.String(length=128), nullable=True))
    port_definition = next(column for column in inspector.get_columns("project_ports") if column["name"] == "port")
    if not port_definition.get("nullable", True):
        op.alter_column("project_ports", "port", existing_type=sa.Integer(), nullable=True)
    if "component" not in port_columns:
        op.add_column("project_ports", sa.Column("component", sa.String(length=255), nullable=True))
    if "port_type" not in port_columns:
        op.add_column("project_ports", sa.Column("port_type", sa.String(length=64), nullable=True))
    if "target_port" not in port_columns:
        op.add_column("project_ports", sa.Column("target_port", sa.Integer(), nullable=True))
    if "service_name" not in port_columns:
        op.add_column("project_ports", sa.Column("service_name", sa.String(length=255), nullable=True))
    if "conflict" not in port_columns:
        op.add_column("project_ports", sa.Column("conflict", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    port_columns = {column["name"] for column in inspector.get_columns("project_ports")}
    component_columns = {column["name"] for column in inspector.get_columns("project_components")}
    for column in ("conflict", "service_name", "target_port", "port_type", "component"):
        if column in port_columns:
            op.drop_column("project_ports", column)
    if "port" in port_columns:
        op.alter_column("project_ports", "port", existing_type=sa.Integer(), nullable=False)
    if "role" in component_columns:
        op.drop_column("project_components", "role")
