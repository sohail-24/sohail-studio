"""Supported technology registry for StackGenerator V1."""

from __future__ import annotations


class StackRegistry:
    """Normalize and validate supported frontend, backend, and database choices."""

    FRONTENDS = {
        "react": "react",
    }

    BACKENDS = {
        "node": "node",
        "node.js": "node",
        "fastapi": "fastapi",
        "django": "django",
        "go": "go",
        "golang": "go",
    }

    DATABASES = {
        "postgresql": "postgresql",
        "postgres": "postgresql",
    }

    def normalize_frontend(self, value: str | None) -> str | None:
        """Normalize a frontend choice."""
        return self._normalize(value, self.FRONTENDS, "frontend")

    def normalize_backend(self, value: str | None) -> str | None:
        """Normalize a backend choice."""
        return self._normalize(value, self.BACKENDS, "backend")

    def normalize_database(self, value: str | None) -> str | None:
        """Normalize a database choice."""
        return self._normalize(value, self.DATABASES, "database")

    @staticmethod
    def _normalize(
        value: str | None,
        allowed: dict[str, str],
        kind: str,
    ) -> str | None:
        if value is None:
            return None

        key = value.strip().lower()
        if key in {"", "none", "undecided"}:
            return None

        if key not in allowed:
            supported = ", ".join(sorted(set(allowed.values())))
            raise ValueError(f"Unsupported {kind} stack: {value}. Supported: {supported}")

        return allowed[key]
