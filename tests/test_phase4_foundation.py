from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config import ConfigurationError, load_config
from core.session_store import SessionStore
from core.storage import Storage, StorageConfig


def test_model_configuration_uses_separate_chat_and_devops_models():
    config = load_config(Path("settings/default.json"), environ={})

    assert config.chat_model == "devops-qwen:v1"
    assert config.devops_model == "devops-qwen:latest"


def test_missing_chat_model_configuration_fails_clearly(tmp_path: Path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"devops_model": "devops-qwen:latest"}', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="CHAT_MODEL is not configured"):
        load_config(settings, environ={})


def test_storage_configuration_reads_database_url_from_environment():
    config = StorageConfig.from_env(
        {"DATABASE_URL": "postgresql://neon-user:secret@ep-example.neon.tech/studio"}
    )

    assert config.database_url.endswith("/studio")
    assert config.sqlalchemy_url.drivername == "postgresql+psycopg"
    assert config.sqlalchemy_url.query["sslmode"] == "require"


def test_storage_initialization_and_health_do_not_require_live_database():
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            return None

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            return None

    storage = Storage(
        StorageConfig.from_env({"DATABASE_URL": "postgresql://user:secret@localhost/studio"}),
        engine=FakeEngine(),
    )

    assert storage.health() == {"database": "connected"}
    storage.close()


def test_health_endpoint_reports_safe_database_state_without_credentials(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import backend.main as main

    response = TestClient(main.app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["database"] == "not_configured"
    assert "DATABASE_URL" not in response.text


def test_existing_json_session_store_behavior_is_preserved(tmp_path: Path):
    store = SessionStore(tmp_path)

    store.write("session-1", {"status": "completed", "output": "safe"})

    sessions = store.list_recent()
    assert len(sessions) == 1
    assert sessions[0]["status"] == "completed"
    assert sessions[0]["output"] == "safe"
    assert "updated_at" in sessions[0]
