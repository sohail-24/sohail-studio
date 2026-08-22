from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_project_intelligence_migration_revision_is_within_alembic_limit():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    script = ScriptDirectory.from_config(config)

    revision_1 = script.get_revision("0001_storage_foundation")
    revision_2 = script.get_revision("0002_project_intelligence")
    revision_3 = script.get_revision("0003_project_intel_refine")

    assert revision_1 is not None
    assert revision_2 is not None
    assert revision_3 is not None
    assert len(revision_3.revision) <= 32
    assert revision_2.down_revision == revision_1.revision
    assert revision_3.down_revision == revision_2.revision
    assert script.get_current_head() == revision_3.revision
