import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from core.evidence import (
    CandidateHypothesis,
    EvidenceAcquisitionService,
    EvidenceAnalysis,
    EvidenceAnalysisEngine,
    EvidenceAnalysisError,
    EvidenceAnalysisStatus,
    EvidenceGap,
    EvidenceOrigin,
    EvidenceReference,
    InspectionTarget,
    is_accepted_evidence_origin,
)
from core.storage.database import Storage, StorageConfig
from core.storage.project_intelligence import ProjectIntelligenceRepository, metadata
from sohail_agent_cli.dockerize import DockerContext, DockerEvidenceGapAdapter
from sohail_agent_cli.inspection import DeepInspector, Evidence, ProjectIntelligence
from sohail_agent_cli.providers import MockProvider


def test_evidence_gap_is_typed_and_preserves_provenance():
    reference = EvidenceReference(
        source_file="frontend/package.json",
        evidence_type="command",
        key="preview",
        confidence="high",
        line_number=4,
    )
    gap = EvidenceGap(
        workflow="Dockerize",
        project="sample",
        root_path="/tmp/sample",
        component="frontend",
        requirement="production runtime",
        reason="No accepted production runtime strategy exists",
        missing_evidence="Production serving strategy",
        observed_evidence=(reference,),
        deterministic_constraints=("No dev commands",),
        allowed_decisions=("Ask for more evidence",),
        forbidden_decisions=("Invent a runtime",),
    )

    payload = gap.to_dict()
    assert payload["component"] == "frontend"
    assert payload["observed_evidence"][0]["source_file"] == "frontend/package.json"
    assert payload["observed_evidence"][0]["origin"] == "REPOSITORY_EVIDENCE"
    assert payload["forbidden_decisions"] == ["Invent a runtime"]


def test_evidence_origins_are_explicit_and_ai_analysis_is_not_accepted():
    assert is_accepted_evidence_origin(EvidenceOrigin.REPOSITORY_EVIDENCE)
    assert is_accepted_evidence_origin(EvidenceOrigin.USER_PROVIDED_EVIDENCE)
    assert is_accepted_evidence_origin(EvidenceOrigin.VERIFIED_INFERENCE)
    assert not is_accepted_evidence_origin(EvidenceOrigin.AI_ANALYSIS)
    assert not is_accepted_evidence_origin("untrusted-origin")

    with pytest.raises(ValueError, match="cannot contain AI_ANALYSIS"):
        EvidenceGap(
            workflow="Dockerize",
            project="sample",
            root_path="/tmp/sample",
            requirement="runtime",
            reason="missing",
            missing_evidence="version",
            observed_evidence=(
                EvidenceReference("analysis", "finding", "runtime", "low", origin=EvidenceOrigin.AI_ANALYSIS),
            ),
        )

    analysis = EvidenceAnalysis(
        status=EvidenceAnalysisStatus.INSPECT_MORE,
        findings=("A relevant configuration file may exist",),
        candidate_hypotheses=(
            CandidateHypothesis(
                statement="A production strategy may be documented",
                confidence="low",
                unsupported_assumptions=("The file exists",),
            ),
        ),
    )
    assert analysis.to_dict()["origin"] == "AI_ANALYSIS"
    with pytest.raises(ValueError, match="must remain AI_ANALYSIS"):
        EvidenceAnalysis(status="blocked", origin=EvidenceOrigin.REPOSITORY_EVIDENCE)


def test_existing_inspector_evidence_remains_compatible():
    evidence = Evidence(
        source_file="package.json",
        evidence_type="command",
        key="start",
        value="python app.py",
        confidence="high",
    )
    assert evidence.to_dict()["source_file"] == "package.json"
    assert "origin" not in evidence.to_dict()


def test_inspection_target_accepts_existing_safe_relative_path(tmp_path: Path):
    target = tmp_path / "config" / "application.yml"
    target.parent.mkdir()
    target.write_text("server:\n  port: 8080\n", encoding="utf-8")

    inspection_target = InspectionTarget(
        relative_path="config/application.yml",
        expected_evidence_type="application_configuration",
        rationale="Verify the application port",
    )

    assert inspection_target.validate(tmp_path) == target.resolve()
    assert inspection_target.to_dict()["relative_path"] == "config/application.yml"


@pytest.mark.parametrize(
    "relative_path, message",
    [
        ("../outside.yml", "path traversal"),
        ("config/../application.yml", "path traversal"),
        ("/tmp/outside.yml", "must be relative"),
        ("python -c 'print(1)'", "shell commands"),
        ("missing.yml", "does not exist"),
        (".env", "may contain secrets"),
        (".git/config", "excluded directory"),
    ],
)
def test_inspection_target_rejects_unsafe_or_missing_paths(tmp_path: Path, relative_path: str, message: str):
    with pytest.raises(ValueError, match=message):
        InspectionTarget(relative_path, "configuration", "test").validate(tmp_path)


def test_dockerize_gap_adapter_represents_current_case_without_changing_decision_behavior(tmp_path: Path):
    context = DockerContext(
        project={
            "name": "sample",
            "root_path": str(tmp_path),
            "selected_components": ["frontend"],
        },
        components=[
            {
                "name": "frontend",
                "path": "frontend",
                "framework": "React",
                "runtimes": [{"runtime": "Node.js", "version": "20", "source_file": ".nvmrc", "confidence": "high"}],
                "commands": [
                    {"name": "dev", "command": "vite", "source_file": "frontend/package.json", "confidence": "high"},
                    {"name": "preview", "command": "vite preview", "source_file": "frontend/package.json", "confidence": "high"},
                ],
                "files": [
                    {"relative_path": "frontend/nginx.conf", "classification": "configuration"},
                ],
            },
        ],
        infrastructure={},
        evidence=[
            {
                "source_file": "frontend/package.json",
                "evidence_type": "framework",
                "key": "framework",
                "value": "React",
                "confidence": "high",
            },
            {
                "source_file": "k8s/frontend-deployment.yml",
                "evidence_type": "port",
                "key": "container_port",
                "value": 80,
                "confidence": "high",
            },
        ],
    )

    gap = DockerEvidenceGapAdapter.from_context(
        context,
        "frontend",
        reason="frontend lacks evidence-backed production start command",
    )

    assert gap.workflow == "Dockerize"
    assert gap.component == "frontend"
    assert gap.requirement == "evidence-backed production Docker runtime/start strategy"
    assert gap.reason.startswith("frontend lacks")
    assert {item.source_file for item in gap.observed_evidence} >= {
        "frontend/package.json",
        ".nvmrc",
        "frontend/nginx.conf",
        "k8s/frontend-deployment.yml",
    }
    assert any("preview" in item.key for item in gap.observed_evidence)
    assert any("preview" in item for item in gap.forbidden_decisions)


def _analysis_response(target: str = "package.json") -> str:
    return json.dumps({
        "status": "inspect_more",
        "findings": ["A repository file may contain the missing runtime strategy"],
        "evidence_relationships": [],
        "inspection_targets": [{
            "relative_path": target,
            "expected_evidence_type": "dependency_manifest",
            "rationale": "Verify repository-owned command evidence",
        }],
        "clarification_questions": [],
        "candidate_hypotheses": [],
        "unsupported_assumptions": ["The target contains the missing fact"],
    })


@pytest.mark.asyncio
async def test_evidence_analysis_is_strict_and_remains_ai_analysis(tmp_path: Path):
    target = tmp_path / "package.json"
    target.write_text('{"scripts":{"start":"python app.py"}}', encoding="utf-8")
    gap = EvidenceGap(
        workflow="Dockerize", project=tmp_path.name, root_path=str(tmp_path), component="application",
        requirement="production runtime", reason="missing", missing_evidence="start strategy",
    )
    analysis = await EvidenceAnalysisEngine(
        MockProvider(responses={"EVIDENCE_GAP": _analysis_response()}), "devops-qwen:latest"
    ).analyze(gap, {"project": tmp_path.name})

    assert analysis.origin is EvidenceOrigin.AI_ANALYSIS
    assert analysis.inspection_targets[0].relative_path == "package.json"
    assert analysis.to_dict()["origin"] == "AI_ANALYSIS"
    with pytest.raises(EvidenceAnalysisError, match="missing field"):
        EvidenceAnalysisEngine._parse_json('{"status":"inspect_more"}')


@pytest.mark.asyncio
async def test_received_invalid_analysis_is_distinguished_from_provider_failure(tmp_path: Path):
    gap = EvidenceGap(
        workflow="Dockerize", project=tmp_path.name, root_path=str(tmp_path),
        requirement="production runtime", reason="missing", missing_evidence="start strategy",
    )

    with pytest.raises(EvidenceAnalysisError) as error:
        await EvidenceAnalysisEngine(
            MockProvider(responses={"EVIDENCE_GAP": '{"status":"inspect_more"}'}),
            "devops-qwen:latest",
        ).analyze(gap, {})

    assert error.value.response_received


def test_evidence_analysis_rejects_malformed_targets_individually():
    payload = json.loads(_analysis_response())
    payload["inspection_targets"] = [
        payload["inspection_targets"][0],
        "malformed target proposal",
        {
            "relative_path": "other.toml",
            "expected_evidence_type": "configuration",
            "rationale": "Check a second repository-owned source",
        },
    ]

    analysis = EvidenceAnalysisEngine._parse_json(json.dumps(payload))

    assert [item.relative_path for item in analysis.inspection_targets] == [
        "package.json", "other.toml",
    ]
    assert analysis.rejected_inspection_targets == (
        {"index": 1, "reason": "inspection target must be an object"},
    )
    assert analysis.origin is EvidenceOrigin.AI_ANALYSIS


def test_evidence_analysis_accepts_required_fields_without_optional_sections():
    analysis = EvidenceAnalysisEngine._parse_json(json.dumps({
        "status": "inspect_more",
        "inspection_targets": [{"relative_path": "package.json"}],
        "evidence_relationships": [{"references": []}],
    }))

    assert [item.relative_path for item in analysis.inspection_targets] == ["package.json"]
    assert analysis.inspection_targets[0].expected_evidence_type == ""
    assert analysis.evidence_relationships[0].description == ""
    assert any("optional description" in item["reason"] for item in analysis.diagnostics)
    assert any(item["field"] == "optional_sections" for item in analysis.diagnostics)


def test_evidence_analysis_preserves_targets_when_optional_items_are_malformed():
    analysis = EvidenceAnalysisEngine._parse_json(json.dumps({
        "status": "inspect_more",
        "inspection_targets": [{"relative_path": "package.json"}],
        "findings": ["useful finding", 42],
        "evidence_relationships": [{"description": "valid"}, "malformed"],
        "clarification_questions": [{"question": "missing requirement"}],
        "candidate_hypotheses": ["malformed"],
        "unsupported_assumptions": ["valid assumption", None],
    }))

    assert len(analysis.inspection_targets) == 1
    assert analysis.findings == ("useful finding",)
    assert len(analysis.evidence_relationships) == 1
    assert not analysis.clarification_questions
    assert analysis.unsupported_assumptions == ("valid assumption",)
    assert {item["field"] for item in analysis.diagnostics} >= {
        "findings", "clarification_questions", "candidate_hypotheses", "unsupported_assumptions",
        "evidence_relationships",
    }


def test_evidence_analysis_extracts_json_from_fences_and_surrounding_text():
    response = (
        "The structured result follows:\n"
        "```json\n"
        '{"status":"inspect_more","inspection_targets":[{"relative_path":"package.json"}]}\n'
        "```\nAdditional explanation is ignored."
    )

    analysis = EvidenceAnalysisEngine._parse_json(response)

    assert analysis.status is EvidenceAnalysisStatus.INSPECT_MORE
    assert analysis.inspection_targets[0].relative_path == "package.json"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ('{"status":"inspect_more"}', "inspection_targets"),
        ('{"status":"inspect_more","inspection_targets":{}}', "must be a list"),
    ],
)
def test_evidence_analysis_missing_required_acquisition_fields_blocks(response: str, message: str):
    with pytest.raises(EvidenceAnalysisError, match=message):
        EvidenceAnalysisEngine._parse_json(response)


def test_targeted_acquisition_persists_only_deterministic_repository_evidence(tmp_path: Path):
    package = tmp_path / "package.json"
    package.write_text('{"scripts":{"start":"python app.py"}}', encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = ProjectIntelligenceRepository(
        Storage(StorageConfig("postgresql://masked@localhost/studio"), engine=engine)
    )
    base = ProjectIntelligence(name=tmp_path.name, root_path=str(tmp_path))
    repository.persist(base)
    gap = EvidenceGap(
        workflow="Dockerize", project=tmp_path.name, root_path=str(tmp_path), component="application",
        requirement="production runtime", reason="missing", missing_evidence="start strategy",
    )
    analysis = EvidenceAnalysisEngine._parse_json(_analysis_response())

    result = EvidenceAcquisitionService(repository).acquire(tmp_path, base, gap, analysis)

    assert result.accepted_evidence_added
    assert result.added_evidence_count > 0
    loaded = repository.load_latest(str(tmp_path))
    assert loaded is not None
    assert any(item.key == "root.start_command" for item in loaded.evidence)
    assert not any(item.evidence_type == "ai_analysis" for item in loaded.evidence)
    repository.storage.close()


def test_targeted_acquisition_stops_when_all_proposals_are_unsafe(tmp_path: Path):
    (tmp_path / "safe.txt").write_text("no structured engineering facts\n", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = ProjectIntelligenceRepository(
        Storage(StorageConfig("postgresql://masked@localhost/studio"), engine=engine)
    )
    base = ProjectIntelligence(name=tmp_path.name, root_path=str(tmp_path))
    repository.persist(base)
    payload = json.loads(_analysis_response("../outside.txt"))
    payload["inspection_targets"].append({
        "relative_path": "missing.txt",
        "expected_evidence_type": "unknown",
        "rationale": "A missing path must not be inspected",
    })

    class MustNotInspect:
        def inspect_targets(self, *_args):
            raise AssertionError("unsafe proposals must not reach DeepInspector")

    result = EvidenceAcquisitionService(repository, inspector=MustNotInspect()).acquire(
        tmp_path,
        base,
        EvidenceGap(
            workflow="Dockerize", project=tmp_path.name, root_path=str(tmp_path),
            component="application",
            requirement="production runtime", reason="missing", missing_evidence="start strategy",
        ),
        EvidenceAnalysisEngine._parse_json(json.dumps(payload)),
    )

    assert result.validated_target_count == 0
    assert not result.verification_performed
    assert len(result.rejected_targets) == 2
    repository.storage.close()


def test_targeted_acquisition_reports_no_new_evidence_without_refreshing_snapshot(tmp_path: Path):
    target = tmp_path / "notes.txt"
    target.write_text("plain notes\n", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = ProjectIntelligenceRepository(
        Storage(StorageConfig("postgresql://masked@localhost/studio"), engine=engine)
    )
    base = ProjectIntelligence(name=tmp_path.name, root_path=str(tmp_path))
    repository.persist(base)
    analysis = EvidenceAnalysisEngine._parse_json(_analysis_response("notes.txt"))

    result = EvidenceAcquisitionService(repository).acquire(
        tmp_path,
        base,
        EvidenceGap(
            workflow="Dockerize", project=tmp_path.name, root_path=str(tmp_path),
            component="application",
            requirement="production runtime", reason="missing", missing_evidence="start strategy",
        ),
        analysis,
    )

    assert result.validated_target_count == 1
    assert result.verification_performed
    assert not result.accepted_evidence_added
    assert result.refreshed is base
    repository.storage.close()


def test_acquisition_merge_deduplicates_structured_metadata_safely():
    base = ProjectIntelligence(
        name="sample",
        root_path="/tmp/sample",
        components=[{"name": "application", "artifacts": [{"path": "one"}]}],
        docker={"files": [{"path": "one"}]},
    )
    partial = ProjectIntelligence(
        name="sample",
        root_path="/tmp/sample",
        components=[{
            "name": "application",
            "artifacts": [{"path": "one"}, {"path": "two"}],
        }],
        docker={"files": [{"path": "one"}, {"path": "two"}]},
    )

    merged = EvidenceAcquisitionService._merge(base, partial)

    assert merged.components[0]["artifacts"] == [{"path": "one"}, {"path": "two"}]
    assert merged.docker["files"] == [{"path": "one"}, {"path": "two"}]


def test_targeted_inspection_does_not_expand_to_unproposed_files(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"scripts":{"start":"python app.py"}}', encoding="utf-8")
    (tmp_path / "secret.txt").write_text("not selected", encoding="utf-8")
    intelligence = DeepInspector().inspect_targets(tmp_path, [tmp_path / "package.json"])

    assert [item.relative_path for item in intelligence.files] == ["package.json"]
    assert all(item.source_file == "package.json" for item in intelligence.evidence)
