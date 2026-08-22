"""Safe PostgreSQL connection and health abstraction.

This module owns database connectivity. It deliberately does not create or
modify schema at application startup; schema changes are applied by Alembic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class StorageConfigurationError(ValueError):
    """Raised when DATABASE_URL is missing or is not a PostgreSQL URL."""


@dataclass(frozen=True)
class StorageConfig:
    """Connection configuration sourced from DATABASE_URL."""

    database_url: str = field(repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "StorageConfig":
        env = os.environ if environ is None else environ
        value = env.get("DATABASE_URL", "").strip()
        if not value:
            raise StorageConfigurationError("DATABASE_URL is not configured")

        try:
            parsed = make_url(value)
        except ArgumentError as exc:
            raise StorageConfigurationError("DATABASE_URL is not a valid database URL") from exc

        if parsed.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise StorageConfigurationError("DATABASE_URL must use PostgreSQL")
        return cls(value)

    @property
    def sqlalchemy_url(self) -> URL:
        """Return a psycopg URL, requiring TLS for Neon hosts."""

        parsed = make_url(self.database_url)
        if parsed.drivername in {"postgres", "postgresql"}:
            parsed = parsed.set(drivername="postgresql+psycopg")
        is_neon = parsed.host and parsed.host.lower().endswith(".neon.tech")
        if is_neon and "sslmode" not in parsed.query:
            parsed = parsed.update_query_dict({"sslmode": "require"})
        return parsed


class Storage:
    """Application-facing PostgreSQL storage boundary."""

    def __init__(self, config: StorageConfig, engine: Engine | None = None) -> None:
        self.config = config
        self.engine = engine or create_engine(
            config.sqlalchemy_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Storage":
        return cls(StorageConfig.from_env(environ))

    def health(self) -> dict[str, str]:
        """Return a credential-free connectivity result."""

        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            return {"database": "unavailable"}
        return {"database": "connected"}

    def close(self) -> None:
        """Release the engine pool without changing database state."""

        self.engine.dispose()
