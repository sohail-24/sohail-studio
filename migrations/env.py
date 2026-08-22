"""Alembic environment using the application's safe storage boundary."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from core.storage import Storage

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    raise RuntimeError("Sohail Studio migrations require a live DATABASE_URL")


def run_migrations_online() -> None:
    storage = Storage.from_env()
    try:
        with storage.engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        storage.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
