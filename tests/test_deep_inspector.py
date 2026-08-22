import json
from pathlib import Path

from sqlalchemy import create_engine, func, select

from core.storage.database import Storage, StorageConfig
from core.storage.project_intelligence import (
    ProjectIntelligenceRepository,
    inspection_runs,
    metadata,
    projects,
)
from sohail_agent_cli.inspection import DeepInspector


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_node_repository(root: Path) -> None:
    write(
        root / "frontend/package.json",
        json.dumps(
            {
                "name": "frontend",
                "engines": {"node": ">=18"},
                "scripts": {"dev": "vite", "build": "vite build", "test": "vitest"},
                "dependencies": {"react": "^18.0.0", "vite": "^5.0.0"},
            }
        ),
    )
    write(root / "frontend/package-lock.json", "{}")
    write(root / "frontend/src/components/App.tsx", "export default function App() { return null; }\n")
    write(
        root / "backend/src/server.js",
        "const PORT = process.env.PORT || 3000;\napp.listen(PORT);\n",
    )
    write(root / "backend/package.json", '{"scripts":{"start":"node src/server.js"},"dependencies":{"express":"^4"}}')
    write(root / "backend/package-lock.json", "{}")
    write(root / "Dockerfile", "FROM node:18\nEXPOSE 3000\n")
    write(root / "docker-compose.yml", "services:\n  backend:\n    ports:\n      - \"3000:3000\"\n")
    write(root / "k8s/base/deployment.yaml", "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: backend\n")
    write(root / "k8s/base/service.yaml", "apiVersion: v1\nkind: Service\nmetadata:\n  name: backend\nspec:\n  ports:\n    - port: 3000\n")
    write(root / ".github/workflows/deploy.yml", "name: deploy\njobs:\n  deploy:\n    runs-on: ubuntu-latest\n")
    write(root / "README.md", "Run Node.js 18 on port 3000.\n")
    write(root / ".nvmrc", "18\n")
    write(root / ".env.example", "PORT=3000\nDATABASE_URL=\n")
    write(root / ".env", "DATABASE_URL=real-secret-value\n")
    write(root / ".git/config", "secret should not be scanned\n")
    write(root / "node_modules/pkg/index.js", "should not be scanned\n")
    write(root / "dist/bundle.js", "should not be scanned\n")


def test_recursive_discovery_exclusions_and_secret_boundary(tmp_path: Path):
    make_node_repository(tmp_path)

    intelligence = DeepInspector().inspect(tmp_path)
    paths = {item.relative_path for item in intelligence.files}
    by_path = {item.relative_path: item for item in intelligence.files}

    assert "frontend/src/components/App.tsx" in paths
    assert "backend/src/server.js" in paths
    assert ".git/config" not in paths
    assert "node_modules/pkg/index.js" not in paths
    assert "dist/bundle.js" not in paths
    assert by_path[".env"].classification == "secret_excluded"
    assert by_path[".env"].sha256 is None
    assert "real-secret-value" not in json.dumps(intelligence.to_dict())
    assert by_path[".env.example"].classification == "environment_example"
    assert by_path["Dockerfile"].classification == "docker"
    assert by_path["docker-compose.yml"].classification == "docker_compose"
    assert by_path["k8s/base/deployment.yaml"].classification == "kubernetes"
    assert by_path[".github/workflows/deploy.yml"].classification == "ci_cd"


def test_manifest_runtime_package_manager_commands_and_frameworks(tmp_path: Path):
    make_node_repository(tmp_path)

    intelligence = DeepInspector().inspect(tmp_path)

    assert "npm" in intelligence.package_managers
    assert "Node.js" in intelligence.languages
    assert "React" in intelligence.frameworks
    assert any(item["runtime"] == "Node.js" and item["version"] == "18" for item in intelligence.runtimes)
    assert any(item["name"] == "build" and item["command"] == "vite build" for item in intelligence.commands)
    assert any(item["name"] == "start" and item["source_file"] == "backend/package.json" for item in intelligence.commands)
    assert any(item["name"] == "react" and item["source_file"] == "frontend/package.json" for item in intelligence.dependencies)


def test_python_manifest_and_evidence_confidence(tmp_path: Path):
    write(
        tmp_path / "pyproject.toml",
        "[project]\nrequires-python = '>=3.11'\ndependencies = ['fastapi>=0.1']\n",
    )
    write(tmp_path / "requirements.txt", "uvicorn>=0.1\n")
    write(tmp_path / "app.py", "app.run(port=8000)\n")

    intelligence = DeepInspector().inspect(tmp_path)

    assert "pip" in intelligence.package_managers
    assert any(item["runtime"] == "Python" and item["confidence"] == "high" for item in intelligence.runtimes)
    assert any(item["name"] == "fastapi" for item in intelligence.dependencies)
    assert any(item["name"] == "root_port" and item["port"] == 8000 for item in intelligence.ports)
    assert all(item.source_file for item in intelligence.evidence)
    assert all(item.confidence in {"high", "medium", "low"} for item in intelligence.evidence)


def test_project_intelligence_normalization_and_reinspection_persistence(tmp_path: Path):
    make_node_repository(tmp_path)
    intelligence = DeepInspector().inspect(tmp_path)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = ProjectIntelligenceRepository(
        Storage(StorageConfig("postgresql://masked@localhost/studio"), engine=engine)
    )

    first = repository.persist(intelligence)
    second = repository.persist(DeepInspector().inspect(tmp_path))

    with engine.connect() as connection:
        project_count = connection.execute(select(func.count()).select_from(projects)).scalar_one()
        run_count = connection.execute(select(func.count()).select_from(inspection_runs)).scalar_one()
        current_run = connection.execute(select(projects.c.current_inspection_id)).scalar_one()

    assert first.project_id == second.project_id
    assert first.run_id != second.run_id
    assert project_count == 1
    assert run_count == 2
    assert current_run == second.run_id


def component_names(intelligence):
    return {item["name"] for item in intelligence.components}


def test_single_backend_does_not_invent_frontend_or_root(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node src/server.js"},"dependencies":{"express":"^4"}}')
    write(tmp_path / "backend/src/server.js", "const PORT = process.env.PORT || 5001; app.listen(PORT);\n")
    write(tmp_path / "backend/.env", "PORT=5001\nMONGO_URI=mongodb://user:secret@localhost/db\nJWT_SECRET=do-not-store\n")

    intelligence = DeepInspector().inspect(tmp_path)

    assert component_names(intelligence) == {"backend"}
    assert not intelligence.has_docker
    assert not intelligence.has_docker_compose
    assert {item["component"] for item in intelligence.ports} == {"backend"}
    assert {item["key"]: item["value"] for item in intelligence.environment_variables}["PORT"] == "5001"
    assert {item["key"]: item["value"] for item in intelligence.environment_variables}["MONGO_URI"] == "REDACTED"
    assert "do-not-store" not in json.dumps(intelligence.to_dict())


def test_single_frontend_does_not_invent_backend_or_root(tmp_path: Path):
    write(tmp_path / "frontend/package.json", '{"scripts":{"dev":"vite"},"dependencies":{"react":"^18","vite":"^5"}}')
    write(tmp_path / "frontend/src/App.jsx", "export default function App() { return null; }\n")
    write(tmp_path / "frontend/vite.config.js", "export default {};\n")

    assert component_names(DeepInspector().inspect(tmp_path)) == {"frontend"}


def test_workspace_root_is_metadata_but_child_apps_are_components(tmp_path: Path):
    write(tmp_path / "package.json", '{"workspaces":["frontend","backend"],"scripts":{"build":"npm run build --prefix frontend"}}')
    write(tmp_path / "frontend/package.json", '{"scripts":{"dev":"vite"},"dependencies":{"react":"^18","vite":"^5"}}')
    write(tmp_path / "frontend/src/App.jsx", "export default function App() { return null; }\n")
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node src/server.js"},"dependencies":{"express":"^4"}}')
    write(tmp_path / "backend/src/server.js", "app.listen(3000);\n")

    assert component_names(DeepInspector().inspect(tmp_path)) == {"backend", "frontend"}


def test_root_node_application_requires_source_evidence(tmp_path: Path):
    write(tmp_path / "package.json", '{"scripts":{"start":"node src/server.js"},"dependencies":{"express":"^4"}}')
    write(tmp_path / "src/server.js", "server.listen(3000);\n")

    intelligence = DeepInspector().inspect(tmp_path)
    assert component_names(intelligence) == {"application"}
    assert intelligence.components[0]["role"] == "application"


def test_django_project_is_backend_only_and_does_not_require_git(tmp_path: Path):
    write(tmp_path / "manage.py", "#!/usr/bin/env python\n")
    write(tmp_path / "pyproject.toml", "[project]\ndependencies=['django>=5']\n")
    write(tmp_path / "project/settings.py", "SECRET_KEY = 'not scanned as source evidence'\n")
    write(tmp_path / "app/views.py", "from django.http import HttpResponse\n")

    intelligence = DeepInspector().inspect(tmp_path)
    assert component_names(intelligence) == {"backend"}
    assert not (tmp_path / ".git").exists()


def test_port_conflicts_remain_explicit_and_provenance_is_retained(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node src/server.js"},"dependencies":{"express":"^4"}}')
    write(tmp_path / "backend/src/server.js", "app.listen(process.env.PORT || 3000);\n")
    write(tmp_path / "backend/.env", "PORT=5001\n")
    write(tmp_path / "README.md", "Backend runs on port 3000.\n")

    intelligence = DeepInspector().inspect(tmp_path)
    application_ports = [item for item in intelligence.ports if item["component"] == "backend" and item["port_type"] == "application"]
    assert len(application_ports) == 1
    assert application_ports[0]["conflict"] is True
    assert application_ports[0]["port"] is None
    assert {candidate["port"] for candidate in application_ports[0]["candidates"]} == {3000, 5001}
    assert {source["source_file"] for source in application_ports[0]["sources"]} >= {"backend/.env", "backend/src/server.js", "README.md"}


def test_explicit_source_listen_port_is_application_evidence(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node src/server.js"},"dependencies":{"express":"^4"}}')
    write(tmp_path / "backend/src/server.js", "server.listen(5001);\n")

    intelligence = DeepInspector().inspect(tmp_path)

    ports = [item for item in intelligence.ports if item["component"] == "backend" and item["port_type"] == "application"]
    assert ports[0]["port"] == 5001
    assert any(source["source_file"] == "backend/src/server.js" for source in ports[0]["sources"])


def test_kubernetes_service_port_is_not_application_port(tmp_path: Path):
    write(
        tmp_path / "k8s/service.yml",
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: backend\nspec:\n  selector:\n    app: backend\n  ports:\n    - port: 5001\n      targetPort: 5001\n",
    )

    intelligence = DeepInspector().inspect(tmp_path)

    assert any(item["port_type"] == "service" and item["port"] == 5001 for item in intelligence.ports)
    assert not any(item["port_type"] == "application" for item in intelligence.ports)


def test_kubernetes_workload_port_is_application_evidence(tmp_path: Path):
    write(
        tmp_path / "k8s/backend.yml",
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: backend\nspec:\n  template:\n    metadata:\n      labels:\n        app: backend\n    spec:\n      containers:\n        - name: api\n          env:\n            - name: PORT\n              value: \"5001\"\n",
    )

    intelligence = DeepInspector().inspect(tmp_path)

    ports = [item for item in intelligence.ports if item["component"] == "backend"]
    assert any(item["port_type"] == "application" and item["port"] == 5001 for item in ports)
    assert any(
        evidence.key == "application_port" and evidence.source_file == "k8s/backend.yml"
        for evidence in intelligence.evidence
    )
