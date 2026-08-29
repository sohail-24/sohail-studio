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
from sohail_agent_cli.inspection import (
    CURRENT_INTELLIGENCE_SCHEMA_VERSION,
    DeepInspector,
    ProjectIntelligence,
)


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
                "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview", "test": "vitest"},
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
    assert any(item["name"] == "preview" and item["command"] == "vite preview" and item["source_file"] == "frontend/package.json" for item in intelligence.commands)
    assert any(item["name"] == "start" and item["source_file"] == "backend/package.json" for item in intelligence.commands)
    assert any(item["name"] == "react" and item["source_file"] == "frontend/package.json" for item in intelligence.dependencies)


def test_repository_nvmrc_runtime_is_inherited_by_node_components(tmp_path: Path):
    make_node_repository(tmp_path)

    intelligence = DeepInspector().inspect(tmp_path)

    for component in ("backend", "frontend"):
        component_data = next(item for item in intelligence.components if item["name"] == component)
        assert {
            (item["runtime"], item["version"], item["source_file"], item["confidence"])
            for item in component_data["runtimes"]
            if item["source_file"] == ".nvmrc"
        } == {("Node.js", "18", ".nvmrc", "high")}


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
    loaded = repository.load_latest(str(tmp_path))
    assert loaded is not None
    assert loaded.intelligence_schema_version == CURRENT_INTELLIGENCE_SCHEMA_VERSION
    assert loaded.data_services == intelligence.data_services
    assert loaded.infrastructure == intelligence.infrastructure
    assert loaded.evidence_gaps == intelligence.evidence_gaps


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
    assert {source["source_file"] for source in application_ports[0]["sources"]} >= {"backend/.env", "backend/src/server.js"}
    assert any(
        item["port_type"] == "documented"
        and item["port"] == 3000
        and any(source["source_file"] == "README.md" for source in item["sources"])
        for item in intelligence.ports
    )


def test_explicit_source_listen_port_is_application_evidence(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node src/server.js"},"dependencies":{"express":"^4"}}')
    write(tmp_path / "backend/src/server.js", "server.listen(5001);\n")

    intelligence = DeepInspector().inspect(tmp_path)

    ports = [item for item in intelligence.ports if item["component"] == "backend" and item["port_type"] == "application"]
    assert ports[0]["port"] == 5001
    assert any(source["source_file"] == "backend/src/server.js" for source in ports[0]["sources"])


def test_dependency_versions_and_machine_node_state_are_not_runtime_evidence(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NODE_VERSION", "22")
    monkeypatch.setenv("npm_config_node_version", "22")
    write(
        tmp_path / "backend/package.json",
        '{"scripts":{"start":"node src/server.js"},"dependencies":{"express":"^20.0.0","mongoose":"^8.0.0"}}',
    )
    write(tmp_path / "backend/src/server.js", "server.listen(5001);\n")

    intelligence = DeepInspector().inspect(tmp_path)

    assert intelligence.runtimes == []


def test_readme_node_range_is_retained_as_non_exact_evidence(tmp_path: Path):
    write(tmp_path / "README.md", "Node.js (v14 or higher)\n")

    intelligence = DeepInspector().inspect(tmp_path)

    assert any(
        item["runtime"] == "Node.js"
        and item["version"] == "v14 or higher"
        and item["source_file"] == "README.md"
        for item in intelligence.runtimes
    )


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
        tmp_path / "backend/package.json",
        '{"scripts":{"start":"node src/server.js"},"dependencies":{"express":"^4"}}',
    )
    write(tmp_path / "backend/src/server.js", "server.listen(process.env.PORT);\n")
    write(
        tmp_path / "k8s/backend-deployment.yml",
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: backend\nspec:\n  template:\n    metadata:\n      labels:\n        app: backend\n    spec:\n      containers:\n        - name: api\n          env:\n            - name: PORT\n              value: \"5001\"\n",
    )
    write(
        tmp_path / "k8s/backend-service.yml",
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: backend\nspec:\n  selector:\n    app: backend\n  ports:\n    - port: 5001\n      targetPort: 5001\n",
    )
    content = (tmp_path / "k8s/backend-deployment.yml").read_text(encoding="utf-8").replace(
        '          env:', '          ports:\n            - containerPort: 5001\n          env:',
    )
    write(tmp_path / "k8s/backend-deployment.yml", content)

    intelligence = DeepInspector().inspect(tmp_path)

    ports = [item for item in intelligence.ports if item["component"] == "backend"]
    assert any(item["port_type"] == "application" and item["port"] == 5001 for item in ports)
    assert any(item["port_type"] == "service" and item["port"] == 5001 for item in ports)
    assert any(
        evidence.key == "container_port" and evidence.source_file == "k8s/backend-deployment.yml"
        for evidence in intelligence.evidence
    )


def test_kubernetes_frontend_port_is_correlated_and_isolated(tmp_path: Path):
    write(tmp_path / "frontend/package.json", '{"scripts":{"preview":"vite preview"},"dependencies":{"vite":"^5"}}')
    write(tmp_path / "frontend/src/main.js", "console.log('frontend');\n")
    write(
        tmp_path / "k8s/frontend-deployment.yml",
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: frontend\nspec:\n  template:\n    metadata:\n      labels:\n        app: frontend\n    spec:\n      containers:\n        - name: frontend\n          ports:\n            - containerPort: 80\n",
    )
    write(
        tmp_path / "k8s/frontend-service.yml",
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: frontend\nspec:\n  selector:\n    app: frontend\n  ports:\n    - port: 80\n      targetPort: 80\n",
    )

    intelligence = DeepInspector().inspect(tmp_path)

    frontend_ports = [item for item in intelligence.ports if item["component"] == "frontend"]
    assert any(item["port_type"] == "application" and item["port"] == 80 for item in frontend_ports)
    assert any(item["port_type"] == "service" and item["port"] == 80 for item in frontend_ports)
    backend_ports = [item for item in intelligence.ports if item["component"] == "backend"]
    assert not any(item.get("port") == 80 for item in backend_ports)


def test_readme_port_without_application_evidence_stays_documented(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node src/server.js"}}')
    write(tmp_path / "backend/src/server.js", "server.listen(process.env.PORT);\n")
    write(tmp_path / "README.md", "The application runs on port 5173.\n")

    intelligence = DeepInspector().inspect(tmp_path)

    assert any(item["port_type"] == "documented" and item["port"] == 5173 for item in intelligence.ports)
    assert not any(item["port_type"] == "application" and item["port"] == 5173 for item in intelligence.ports)


def test_data_services_are_generic_and_support_multiple_verified_services(tmp_path: Path):
    write(tmp_path / "backend/package.json", json.dumps({
        "scripts": {"start": "node server.js"},
        "dependencies": {"express": "^4", "pg": "^8", "ioredis": "^5", "@prisma/client": "^5"},
    }))
    write(tmp_path / "backend/server.js", "app.listen(process.env.PORT || 3000);\n")
    write(tmp_path / "backend/prisma/schema.prisma", 'datasource db { provider = "postgresql" url = env("DATABASE_URL") }\n')
    write(tmp_path / "backend/migrations/001.sql", "create table users(id integer);\n")
    write(tmp_path / ".env.example", "DATABASE_URL=\nREDIS_URL=\n")

    intelligence = DeepInspector().inspect(tmp_path)

    services = {(item["service_type"], item["role"]) for item in intelligence.data_services}
    assert ("PostgreSQL", "database") in services
    assert ("Redis", "cache") in services
    assert any(item["client_or_library"] and "Prisma" in item["client_or_library"] for item in intelligence.data_services)
    postgres = next(item for item in intelligence.data_services if item["service_type"] == "PostgreSQL")
    assert "DATABASE_URL" in postgres["configuration_variables"]
    assert "backend/prisma/schema.prisma" in postgres["schema_or_model_locations"]
    assert "backend/migrations/001.sql" in postgres["migration_locations"]
    assert all("mongodb_detected" not in item and "mongodb_uri" not in item for item in intelligence.data_services)


def test_no_data_service_is_explicitly_empty_without_invention(tmp_path: Path):
    write(tmp_path / "app.py", "print('hello')\n")

    intelligence = DeepInspector().inspect(tmp_path)

    assert intelligence.data_services == []
    assert intelligence.databases == []
    assert intelligence.to_dict()["data_services"] == []


def test_environment_contract_tracks_sources_defaults_and_missing_values_without_secrets(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node server.js"}}')
    write(tmp_path / "backend/server.js", "const url = process.env.API_URL || 'http://localhost:9000'; const secret = process.env.JWT_SECRET;\n")
    write(tmp_path / ".env.example", "API_URL=\nJWT_SECRET=\n")
    write(tmp_path / ".env", "API_URL=http://private.local\nJWT_SECRET=real-secret\n")

    intelligence = DeepInspector().inspect(tmp_path)
    variables = {item["name"]: item for item in intelligence.environment_variables}

    assert variables["API_URL"]["required"] is False
    assert variables["API_URL"]["value"] == "http://private.local"
    assert "backend/server.js" in variables["API_URL"]["source_files"]
    assert variables["JWT_SECRET"]["sensitive"] is True
    assert variables["JWT_SECRET"]["value"] == "REDACTED"
    assert variables["JWT_SECRET"]["value_status"] == "AVAILABLE_REDACTED"
    assert "real-secret" not in json.dumps(intelligence.to_dict())
    assert not any(gap.get("name") == "JWT_SECRET" for gap in intelligence.evidence_gaps)
    assert not any(item["name"] == "JWT_SECRET" for item in intelligence.project_setup["requirements"])


def test_missing_environment_value_creates_actionable_setup_requirement_and_safe_template(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node server.js"}}')
    write(tmp_path / "backend/server.js", "server.listen(process.env.PORT); const key = process.env.API_KEY;\n")

    intelligence = DeepInspector().inspect(tmp_path)

    requirements = {item["name"]: item for item in intelligence.project_setup["requirements"]}
    assert intelligence.project_setup["status"] == "NEEDS_EVIDENCE"
    assert requirements["PORT"]["value_status"] == "NEEDS_EVIDENCE"
    assert requirements["PORT"]["resolution"] == "USER_CONFIGURATION_REQUIRED"
    assert requirements["PORT"]["blocks"] == ["dockerfile", "compose", "kubernetes"]
    assert requirements["API_KEY"]["sensitive"] is True
    assert requirements["API_KEY"]["value"] is None
    template = next(item for item in intelligence.project_setup["templates"] if item["component"] == "backend")
    assert "PORT=<provide value>" in template["content"]
    assert "API_KEY=<provide your secret value>" in template["content"]
    assert template["commands"] == []
    assert template["location"]["status"] == "NEEDS_EVIDENCE"
    assert "API_KEY=real-secret" not in json.dumps(intelligence.project_setup)


def test_environment_example_is_template_evidence_not_verified_runtime_value(tmp_path: Path):
    write(tmp_path / "backend/server.js", "server.listen(process.env.PORT);\n")
    write(tmp_path / ".env.example", "PORT=3000\n")

    intelligence = DeepInspector().inspect(tmp_path)

    variable = next(item for item in intelligence.environment_variables if item["name"] == "PORT")
    assert variable["value_status"] == "TEMPLATE_ONLY"
    assert any(item["name"] == "PORT" for item in intelligence.project_setup["requirements"])
    assert intelligence.project_setup["requirements"][0]["value"] is None
    assert intelligence.project_setup["templates"][0]["location"] == {
        "status": "VERIFIED",
        "path": ".env",
        "sources": [".env.example"],
        "basis": "explicit repository env file, template, or setup instruction",
    }
    assert intelligence.project_setup["templates"][0]["commands"] == ["cp .env.example .env"]
    assert "PORT=3000" in intelligence.project_setup["templates"][0]["content"]


def test_explicit_source_default_is_recorded_without_setup_gap(tmp_path: Path):
    write(tmp_path / "server.js", "server.listen(process.env.PORT || 4100);\n")

    intelligence = DeepInspector().inspect(tmp_path)

    variable = next(item for item in intelligence.environment_variables if item["name"] == "PORT")
    assert variable["value_status"] == "DEFAULT_ONLY"
    assert variable["value"] == "4100"
    assert not any(item["name"] == "PORT" for item in intelligence.project_setup["requirements"])


def test_reinspection_updates_setup_from_missing_to_verified_without_trusting_user_claim(tmp_path: Path):
    write(tmp_path / "backend/server.js", "server.listen(process.env.PORT);\n")
    first = DeepInspector().inspect(tmp_path)
    assert any(item["name"] == "PORT" for item in first.project_setup["requirements"])

    write(tmp_path / "backend/.env", "PORT=5001\n")
    second = DeepInspector().inspect(tmp_path)
    variable = next(item for item in second.environment_variables if item["name"] == "PORT")
    assert variable["value_status"] == "AVAILABLE"
    assert variable["value"] == "5001"
    assert not any(item["name"] == "PORT" for item in second.project_setup["requirements"])


def test_persisted_reinspection_reconciles_active_setup_and_is_idempotent(tmp_path: Path):
    write(tmp_path / "README.md", "Setup:\ntouch .env\nMYSQL_DB=your_database\nMYSQL_PASSWORD=your_password\n")
    write(tmp_path / "app.py", "import os\nos.environ.get('MYSQL_DB')\nos.environ.get('MYSQL_PASSWORD')\n")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = ProjectIntelligenceRepository(
        Storage(StorageConfig("postgresql://masked@localhost/studio"), engine=engine)
    )

    first = DeepInspector().inspect(tmp_path)
    first_persisted = repository.persist(first)
    assert repository.load_latest(str(tmp_path)).project_setup["requirements"]

    write(tmp_path / ".env", "MYSQL_DB=devops\nMYSQL_PASSWORD=local-secret\n")
    second = DeepInspector().inspect(tmp_path)
    second_persisted = repository.persist(second)
    loaded = repository.load_latest(str(tmp_path))

    assert second_persisted.run_id != first_persisted.run_id
    assert loaded is not None
    assert loaded.inspection_run_id == second_persisted.run_id
    assert loaded.project_setup["status"] == "READY"
    assert loaded.project_setup["requirements"] == []
    password = next(item for item in loaded.environment_variables if item["name"] == "MYSQL_PASSWORD")
    assert password["value_status"] == "AVAILABLE_REDACTED"
    assert password["value"] == "REDACTED"
    assert "local-secret" not in json.dumps(loaded.to_dict())

    third = DeepInspector().inspect(tmp_path)
    third_persisted = repository.persist(third)
    latest = repository.load_latest(str(tmp_path))
    assert third_persisted.run_id != second_persisted.run_id
    assert latest is not None
    assert latest.project_setup["status"] == "READY"
    assert latest.project_setup["requirements"] == []


def test_readme_setup_evidence_promotes_only_concise_immediate_configuration(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node server.js"}}')
    write(
        tmp_path / "backend/server.js",
        "server.listen(process.env.PORT); connect(process.env.MONGODB_URI); sign(process.env.JWT_SECRET); upload(process.env.CLOUDINARY_API_KEY);\n",
    )
    write(
        tmp_path / "README.md",
        "Setup:\ncd backend\ncreate .env\nMONGODB_URI=mongodb://user:secret@localhost/db\nJWT_SECRET=your_jwt_secret_key\nPORT=5001\n",
    )

    intelligence = DeepInspector().inspect(tmp_path)
    setup = intelligence.project_setup

    immediate = {item["name"]: item for item in setup["immediate_requirements"]}
    additional = {item["name"]: item for item in setup["additional_requirements"]}
    assert set(immediate) == {"JWT_SECRET", "MONGODB_URI", "PORT"}
    assert "CLOUDINARY_API_KEY" in additional
    template = next(item for item in setup["immediate_templates"] if item["component"] == "backend")
    assert template["location"]["path"] == "backend/.env"
    assert template["commands"] == ["touch .env"]
    assert "PORT=5001" in template["content"]
    assert "mongodb://user:secret" not in json.dumps(setup)
    assert "your_jwt_secret_key" not in json.dumps(setup)


def test_readme_only_configuration_is_actionable_without_promoting_examples_to_values(tmp_path: Path):
    write(
        tmp_path / "README.md",
        """Setup the project:\ncd your-repo-name\ntouch .env\n
MYSQL_HOST=mysql\nMYSQL_USER=your_username\nMYSQL_PASSWORD=your_password\nMYSQL_DB=your_database\n""",
    )

    setup = DeepInspector().inspect(tmp_path).project_setup

    assert setup["status"] == "NEEDS_EVIDENCE"
    assert {item["name"] for item in setup["immediate_requirements"]} == {
        "MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DB",
    }
    assert set(setup["immediate_templates"][0]["variables"]) == {
        "MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DB",
    }
    template = setup["immediate_templates"][0]
    assert template["location"]["path"] == ".env"
    assert template["commands"] == ["touch .env"]
    assert "MYSQL_HOST=mysql" in template["content"]
    assert "your_username" not in json.dumps(setup)
    assert "your_password" not in json.dumps(setup)
    assert "your_database" not in json.dumps(setup)
    assert all(item["value"] is None for item in setup["requirements"])


def test_missing_environment_location_is_not_guessed(tmp_path: Path):
    write(tmp_path / "backend/server.js", "server.listen(process.env.PORT);\n")

    setup = DeepInspector().inspect(tmp_path).project_setup
    requirement = next(item for item in setup["requirements"] if item["name"] == "PORT")

    assert requirement["location"]["status"] == "NEEDS_EVIDENCE"
    assert requirement["location"]["path"] is None
    template = next(item for item in setup["templates"] if item["component"] == "backend")
    assert template["commands"] == []


def test_dependency_name_alone_is_not_verified_as_a_data_service(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node server.js"},"dependencies":{"pg":"^8"}}')
    write(tmp_path / "backend/server.js", "console.log('no connection configured here');\n")

    intelligence = DeepInspector().inspect(tmp_path)

    postgres = next(item for item in intelligence.data_services if item["service_type"] == "PostgreSQL")
    assert postgres["status"] == "NEEDS_EVIDENCE"
    assert postgres["evidence_basis"] == ["client or library dependency only"]
    assert any(gap["kind"] == "data_service" and gap["name"] == "PostgreSQL" for gap in intelligence.evidence_gaps)


def test_generic_configuration_does_not_choose_between_multiple_data_service_clients(tmp_path: Path):
    write(tmp_path / "backend/package.json", json.dumps({
        "scripts": {"start": "node server.js"},
        "dependencies": {"pg": "^8", "mysql2": "^3"},
    }))
    write(tmp_path / "backend/server.js", "connect(process.env.DATABASE_URL);\n")
    write(tmp_path / ".env.example", "DATABASE_URL=\n")

    intelligence = DeepInspector().inspect(tmp_path)

    candidates = [
        item for item in intelligence.data_services
        if item["service_type"] in {"PostgreSQL", "MySQL"}
    ]
    assert {item["status"] for item in candidates} == {"AMBIGUOUS"}
    assert any(item["kind"] == "data_service" and item["status"] == "CONTRADICTORY" for item in intelligence.contradictions)


def test_build_outputs_entrypoints_and_workspace_membership_are_explicit(tmp_path: Path):
    write(tmp_path / "package.json", json.dumps({"workspaces": ["packages/*"], "private": True}))
    write(tmp_path / "packages/web/package.json", json.dumps({
        "scripts": {"build": "vite build --outDir public", "start": "node src/server.js"},
        "dependencies": {"vite": "^5"},
    }))
    write(tmp_path / "packages/web/src/server.js", "console.log('server');\n")

    intelligence = DeepInspector().inspect(tmp_path)

    web = next(item for item in intelligence.components if item["name"] == "web")
    assert any(item.get("outputs") == ["public"] for item in intelligence.build_metadata)
    assert any(item["value"] == "src/server.js" for item in intelligence.entrypoints)
    assert any(
        item["relationship_type"] == "workspace_member" and item["target"] == "web"
        for item in intelligence.relationships
    )
    assert any(item["name"] == "build" and item["purpose"] == "build" for item in web["commands"])


def test_network_types_relationships_infrastructure_and_contradictions_are_preserved(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node server.js","prod":"node alternate.js"}}')
    write(tmp_path / "backend/server.js", "app.listen(3000);\n")
    write(tmp_path / "frontend/package.json", '{"scripts":{"build":"vite build"},"dependencies":{"vite":"^5"}}')
    write(tmp_path / "frontend/src/main.js", "fetch(import.meta.env.BACKEND_URL);\n")
    write(tmp_path / "frontend/nginx.conf", "server { listen 80; location / { proxy_pass http://backend:3000; } }\n")
    write(tmp_path / "Dockerfile", "FROM node:20\nEXPOSE 3000\n")
    write(tmp_path / "compose.yml", "services:\n  backend:\n    build: .\n    ports:\n      - '8080:3000'\n")
    write(tmp_path / "k8s/service.yml", "apiVersion: v1\nkind: Service\nmetadata:\n  name: backend\nspec:\n  ports:\n    - port: 80\n      targetPort: 3000\n")

    intelligence = DeepInspector().inspect(tmp_path)
    port_types = {item["port_type"] for item in intelligence.ports}

    assert {"application", "proxy", "container", "service"}.issubset(port_types)
    service_ports = [item for item in intelligence.ports if item["port_type"] == "service" and item["component"] == "backend"]
    assert service_ports[0]["conflict"] is True
    assert {candidate["port"] for candidate in service_ports[0]["candidates"]} == {80, 8080}
    assert any(item["relationship_type"] == "frontend_to_backend" for item in intelligence.relationships)
    proxy_relationship = next(item for item in intelligence.relationships if item["relationship_type"] == "proxy_to_upstream")
    assert proxy_relationship["target"] == "backend"
    assert proxy_relationship["target_port"] == 3000
    assert any(item["type"] == "reverse_proxy" and item["status"] == "unknown" for item in intelligence.infrastructure)
    assert any(item["type"] == "container_orchestration" and item["status"] == "referenced" for item in intelligence.infrastructure)
    assert any(item["kind"] == "command" and item["status"] == "CONTRADICTORY" for item in intelligence.contradictions)


def test_old_summary_is_marked_incomplete_instead_of_claiming_new_intelligence():
    intelligence = ProjectIntelligence.from_summary(
        {"project": "old", "components": [], "evidence": []},
        root_path="/tmp/old",
        inspection_run_id="old-run",
    )

    payload = intelligence.to_dict()
    assert payload["intelligence_schema_version"] == 1
    assert payload["intelligence_status"] == "NEEDS_EVIDENCE"
    assert any(item["kind"] == "snapshot_schema" for item in payload["evidence_gaps"])


def test_schema_two_snapshot_is_not_reinterpreted_as_current():
    intelligence = ProjectIntelligence.from_summary(
        {"project": "older", "intelligence_schema_version": 2, "components": [], "evidence": []},
        root_path="/tmp/older",
        inspection_run_id="older-run",
    )

    payload = intelligence.to_dict()
    assert payload["intelligence_schema_version"] == 2
    assert payload["intelligence_status"] == "NEEDS_EVIDENCE"
    gap = next(item for item in payload["evidence_gaps"] if item["kind"] == "snapshot_schema")
    assert gap["resolution"] == "reinspect_repository"
