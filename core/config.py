"""Small, explicit runtime configuration for Sohail Studio."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigurationError(ValueError):
    """Raised when a required Studio setting is missing or empty."""


@dataclass(frozen=True)
class StudioConfig:
    """Runtime settings shared by the Studio backend and future generators."""

    chat_model: str
    devops_model: str
    ollama_base_url: str


def load_config(
    settings_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> StudioConfig:
    """Load JSON defaults with environment overrides."""

    env = os.environ if environ is None else environ
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        settings = {}

    def required(name: str, setting_key: str) -> str:
        value = env.get(name)
        if value is None:
            value = settings.get(setting_key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"{name} is not configured")
        return value.strip()

    base_url = env.get("OLLAMA_BASE_URL") or settings.get(
        "ollama_base_url", "http://localhost:11434"
    )
    if not isinstance(base_url, str) or not base_url.strip():
        raise ConfigurationError("OLLAMA_BASE_URL is not configured")

    return StudioConfig(
        chat_model=required("CHAT_MODEL", "chat_model"),
        devops_model=required("DEVOPS_MODEL", "devops_model"),
        ollama_base_url=base_url.strip(),
    )
