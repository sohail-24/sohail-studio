"""Run the reproducible PostgreSQL schema migration."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def upgrade_database(revision: str = "head") -> None:
    """Apply migrations up to *revision* using DATABASE_URL."""

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, revision)


if __name__ == "__main__":
    upgrade_database()
