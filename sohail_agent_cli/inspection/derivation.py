"""Deterministic derivation of deployable facts from structured inspection facts.

This module deliberately accepts structured facts produced by Inspect.  It does
not open repository files and is therefore safe to run before persistence or in
tests against a previously extracted snapshot.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .models import Evidence, EvidenceSourceType, ProjectIntelligence


MAVEN_ARTIFACT_RULE = "maven.executable-artifact.spring-boot.v1"
MAVEN_PACKAGING_RULE = "maven.default-packaging.jar.v1"
MAVEN_FINAL_NAME_RULE = "maven.default-final-name.v1"
MAVEN_DIRECTORY_RULE = "maven.default-build-directory.v1"
SPRING_BOOT_PARENT_RULE = "spring-boot.parent-repackage.v1"
GRADLE_ARTIFACT_RULE = "gradle.executable-artifact.spring-boot.v1"
GO_ARTIFACT_RULE = "go.explicit-build-output.v1"
RUST_ARTIFACT_RULE = "rust.single-package-binary.v1"


def _ref(source_file: str, key: str, value: Any = None) -> dict[str, Any]:
    result = {"source_file": source_file, "key": key}
    if value is not None:
        result["value"] = value
    return result


def _evidence(
    *,
    source_file: str,
    key: str,
    value: Any,
    rule_id: str | None = None,
    derived_from: Iterable[dict[str, Any]] = (),
    source_type: str = EvidenceSourceType.DERIVED_DETERMINISTIC,
    confidence: str = "deterministic",
) -> Evidence:
    return Evidence(
        source_file=source_file,
        evidence_type="deployment_artifact" if source_type != EvidenceSourceType.UNSUPPORTED else "unsupported_requirement",
        key=key,
        value=value,
        confidence=confidence,
        extraction_method="deterministic-derivation",
        source_type=source_type,
        derived_from=list(derived_from),
        rule_id=rule_id,
        model_inference=False,
    )


def _component_path(component: dict[str, Any]) -> str:
    path = str(component.get("path") or ".").strip("./")
    return path or "."


def _belongs(source_file: str, component: dict[str, Any]) -> bool:
    path = _component_path(component)
    return path == "." or source_file == path or source_file.startswith(path + "/")


def _metadata_for(component: dict[str, Any], metadata: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item for item in metadata
        if _belongs(str(item.get("source_file") or ""), component)
    ]


def _entrypoints_for(component: dict[str, Any], entrypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item for item in entrypoints
        if _belongs(str(item.get("source_file") or ""), component)
        and str(item.get("kind") or "") == "java_main_class"
    ]


def _unsupported(
    intelligence: ProjectIntelligence,
    component: dict[str, Any],
    reason: str,
    *,
    source_file: str = "pom.xml",
    derived_from: Iterable[dict[str, Any]] = (),
) -> None:
    component.setdefault("artifacts", [])
    component["deployment_evidence"] = {
        "status": EvidenceSourceType.UNSUPPORTED,
        "reason": reason,
        "source_type": EvidenceSourceType.UNSUPPORTED,
        "derived_from": list(derived_from),
        "rule_id": MAVEN_ARTIFACT_RULE,
        "confidence": "unsupported",
        "model_inference": False,
    }
    intelligence.evidence.append(_evidence(
        source_file=source_file,
        key=f"{component.get('name')}.production_artifact",
        value={"status": EvidenceSourceType.UNSUPPORTED, "reason": reason},
        source_type=EvidenceSourceType.UNSUPPORTED,
        derived_from=derived_from,
    ))


def _resolve_local_value(
    value: Any,
    metadata: dict[str, Any],
    parent_by_source: dict[str, dict[str, Any]],
    field: str,
) -> str | None:
    if str(value or "").strip():
        return str(value).strip()
    parent_source = str(metadata.get("parent_source_file") or "")
    parent = parent_by_source.get(parent_source)
    if parent and str(parent.get(field) or "").strip():
        return str(parent[field]).strip()
    return None


def _single_value(values: list[str | None]) -> tuple[str | None, bool]:
    present = {str(value).strip() for value in values if str(value or "").strip()}
    return (next(iter(present)) if len(present) == 1 else None, len(present) <= 1)


def _derive_maven(
    intelligence: ProjectIntelligence,
    component: dict[str, Any],
    metadata: list[dict[str, Any]],
    parent_by_source: dict[str, dict[str, Any]],
) -> None:
    if len(metadata) != 1:
        _unsupported(
            intelligence, component,
            "Maven component is ambiguous because its selected component maps to multiple POM files",
            derived_from=[_ref(str(item.get("source_file") or "pom.xml"), "pom") for item in metadata],
        )
        return
    pom = metadata[0]
    source = str(pom.get("source_file") or "pom.xml")
    refs = [_ref(source, key) for key in (
        "groupId", "artifactId", "version", "packaging", "build.finalName",
        "build.directory", "spring-boot-maven-plugin", "spring-boot.repackage",
    )]
    group_id = _resolve_local_value(pom.get("group_id"), pom, parent_by_source, "group_id")
    artifact_id = str(pom.get("artifact_id") or "").strip()
    version = _resolve_local_value(pom.get("version"), pom, parent_by_source, "version")
    packaging = str(pom.get("packaging") or "jar").strip()
    if not group_id or not artifact_id or not version:
        _unsupported(intelligence, component, "Maven coordinates are incomplete or inherited from an unavailable parent", source_file=source, derived_from=refs)
        return
    if packaging not in {"jar", "war"}:
        _unsupported(intelligence, component, f"Maven packaging '{packaging}' does not prove an executable application artifact", source_file=source, derived_from=refs)
        return
    if packaging == "war":
        _unsupported(intelligence, component, "Maven WAR packaging requires an independently proven container launch strategy", source_file=source, derived_from=refs)
        return
    modules = [str(item).strip() for item in pom.get("modules") or [] if str(item).strip()]
    if modules or int(pom.get("pom_count") or 1) != 1:
        _unsupported(intelligence, component, "Maven project is multi-module; the exact deployable module artifact is not selected", source_file=source, derived_from=refs)
        return

    plugins = [item for item in pom.get("plugins") or [] if item.get("artifact_id") == "spring-boot-maven-plugin"]
    if len(plugins) != 1 or str(plugins[0].get("group_id") or "") != "org.springframework.boot":
        _unsupported(intelligence, component, "The Spring Boot Maven plugin is absent or has an ambiguous groupId", source_file=source, derived_from=refs)
        return
    plugin = plugins[0]
    executions = list(plugin.get("executions") or [])
    explicit_repackage = [execution for execution in executions if "repackage" in execution.get("goals", [])]
    parent = pom.get("parent") or {}
    boot_parent = (
        parent.get("group_id") == "org.springframework.boot"
        and parent.get("artifact_id") == "spring-boot-starter-parent"
    )
    if not explicit_repackage and not boot_parent:
        _unsupported(intelligence, component, "Spring Boot repackage execution is not explicitly present and no locally identified Spring Boot parent supplies it", source_file=source, derived_from=refs)
        return
    if len(explicit_repackage) > 1:
        _unsupported(intelligence, component, "Multiple Spring Boot repackage executions make the executable artifact ambiguous", source_file=source, derived_from=refs)
        return
    configurations = [plugin.get("configuration") or {}]
    configurations.extend(execution.get("configuration") or {} for execution in explicit_repackage)
    layouts = {str(item.get("layout")).strip() for item in configurations if str(item.get("layout") or "").strip()}
    if "NONE" in layouts:
        _unsupported(intelligence, component, "Spring Boot repackage layout=NONE does not prove a java -jar executable", source_file=source, derived_from=refs)
        return
    if any(str(item.get("skip") or "").strip().lower() == "true" for item in configurations):
        _unsupported(intelligence, component, "Spring Boot repackage is explicitly disabled", source_file=source, derived_from=refs)
        return
    classifiers = {str(item.get("classifier") or "").strip() for item in configurations if str(item.get("classifier") or "").strip()}
    if len(classifiers) > 1:
        _unsupported(intelligence, component, "Conflicting Spring Boot repackage classifiers prevent exact artifact selection", source_file=source, derived_from=refs)
        return
    final_name = str(pom.get("build_final_name") or "").strip()
    final_rule = None
    if not final_name:
        final_name = f"{artifact_id}-{version}"
        final_rule = MAVEN_FINAL_NAME_RULE
    if "${" in final_name or "}" in final_name:
        _unsupported(intelligence, component, "Maven build.finalName contains an unresolved expression", source_file=source, derived_from=refs)
        return
    directory = str(pom.get("build_directory") or "").strip() or "target"
    if "${" in directory or "}" in directory:
        _unsupported(intelligence, component, "Maven build.directory contains an unresolved expression", source_file=source, derived_from=refs)
        return
    classifier = next(iter(classifiers), "")
    filename = f"{final_name}{('-' + classifier) if classifier else ''}.{packaging}"
    artifact_path = f"{directory.rstrip('/')}/{filename}"
    entrypoints = _entrypoints_for(component, intelligence.entrypoints)
    configured_main = next(
        (str(item.get("mainClass") or item.get("main_class")).strip()
         for item in configurations if str(item.get("mainClass") or item.get("main_class") or "").strip()),
        None,
    )
    if not configured_main and len(entrypoints) != 1:
        _unsupported(intelligence, component, "Spring Boot executable main class is not uniquely proven", source_file=source, derived_from=refs)
        return
    main_class = configured_main or str(entrypoints[0].get("class_name"))
    derived_from = list(refs)
    if final_rule:
        derived_from.append(_ref(source, "artifactId/version", f"{artifact_id}/{version}"))
    if directory == "target" and not pom.get("build_directory"):
        derived_from.append(_ref(source, "Maven default build directory", "target"))
    if boot_parent and not explicit_repackage:
        derived_from.append(_ref(source, "spring-boot-starter-parent", "repackage execution"))
    artifact = {
        "path": artifact_path,
        "filename": filename,
        "packaging": packaging,
        "classifier": classifier or None,
        "executable": True,
        "main_class": main_class,
        "launch_command": ["java", "-jar", artifact_path],
        "source_type": EvidenceSourceType.DERIVED_DETERMINISTIC,
        "derived_from": derived_from,
        "rule_id": MAVEN_ARTIFACT_RULE,
        "confidence": "deterministic",
        "model_inference": False,
    }
    component["artifacts"] = [artifact]
    component["deployment_evidence"] = {
        "status": EvidenceSourceType.DERIVED_DETERMINISTIC,
        "source_type": EvidenceSourceType.DERIVED_DETERMINISTIC,
        "derived_from": derived_from,
        "rule_id": MAVEN_ARTIFACT_RULE,
        "confidence": "deterministic",
        "model_inference": False,
        "packaging": packaging,
        "artifact_path": artifact_path,
        "production_start_command": "java -jar " + artifact_path,
    }
    intelligence.evidence.extend([
        _evidence(source_file=source, key=f"{component.get('name')}.packaging", value=packaging, rule_id=MAVEN_PACKAGING_RULE, derived_from=refs),
        _evidence(source_file=source, key=f"{component.get('name')}.executable_artifact", value=artifact, rule_id=MAVEN_ARTIFACT_RULE, derived_from=derived_from),
        _evidence(source_file=source, key=f"{component.get('name')}.production_start_command", value=artifact["launch_command"], rule_id=MAVEN_ARTIFACT_RULE, derived_from=derived_from),
    ])


def _set_compiled_artifact(
    intelligence: ProjectIntelligence,
    component: dict[str, Any],
    *,
    path: str,
    packaging: str,
    launch_command: list[str],
    rule_id: str,
    source_file: str,
    derived_from: list[dict[str, Any]],
) -> None:
    artifact = {
        "path": path,
        "filename": path.rsplit("/", 1)[-1],
        "packaging": packaging,
        "classifier": None,
        "executable": True,
        "launch_command": launch_command,
        "source_type": EvidenceSourceType.DERIVED_DETERMINISTIC,
        "derived_from": derived_from,
        "rule_id": rule_id,
        "confidence": "deterministic",
        "model_inference": False,
    }
    component["artifacts"] = [artifact]
    component["deployment_evidence"] = {
        "status": EvidenceSourceType.DERIVED_DETERMINISTIC,
        "source_type": EvidenceSourceType.DERIVED_DETERMINISTIC,
        "derived_from": derived_from,
        "rule_id": rule_id,
        "confidence": "deterministic",
        "model_inference": False,
        "artifact_path": path,
        "production_start_command": " ".join(launch_command),
    }
    intelligence.evidence.extend([
        _evidence(
            source_file=source_file,
            key=f"{component.get('name')}.executable_artifact",
            value=artifact,
            rule_id=rule_id,
            derived_from=derived_from,
        ),
        _evidence(
            source_file=source_file,
            key=f"{component.get('name')}.production_start_command",
            value=launch_command,
            rule_id=rule_id,
            derived_from=derived_from,
        ),
    ])


def _derive_gradle(
    intelligence: ProjectIntelligence,
    component: dict[str, Any],
    metadata: list[dict[str, Any]],
) -> None:
    builds = [item for item in metadata if not item.get("settings")]
    settings = [item for item in metadata if item.get("settings")]
    if len(builds) != 1 or any(item.get("modules") for item in settings):
        _unsupported(intelligence, component, "Gradle project is ambiguous or multi-module; one deployable module is required", source_file=str((builds or settings or [{}])[0].get("source_file") or "build.gradle"))
        return
    build = builds[0]
    source = str(build.get("source_file") or "build.gradle")
    if not build.get("spring_boot_plugin") or "java" not in {str(item.get("id")) for item in build.get("plugins") or []}:
        _unsupported(intelligence, component, "Gradle Spring Boot and Java plugins are not both proven", source_file=source)
        return
    if not build.get("main_class") and len(_entrypoints_for(component, intelligence.entrypoints)) != 1:
        _unsupported(intelligence, component, "Gradle executable main class is not uniquely proven", source_file=source)
        return
    version = str(build.get("version") or "").strip()
    project_name = next((str(item.get("root_project_name") or "").strip() for item in settings if item.get("root_project_name")), "")
    archive = str(build.get("archive_file_name") or "").strip()
    if archive:
        filename = archive if archive.endswith(".jar") else archive + ".jar"
        refs = [_ref(source, "bootJar.archiveFileName", archive)]
    elif project_name and version and build.get("archive_base_name") is None:
        filename = f"{project_name}-{version}.jar"
        refs = [_ref(source, "settings.rootProject.name", project_name), _ref(source, "version", version), _ref(source, "Gradle default build/libs", "build/libs")]
    else:
        _unsupported(intelligence, component, "Gradle archive filename is not exactly proven by rootProject.name/version or archiveFileName", source_file=source)
        return
    main_class = str(build.get("main_class") or _entrypoints_for(component, intelligence.entrypoints)[0].get("class_name"))
    refs.extend([
        _ref(source, "spring-boot plugin", "bootJar"),
        _ref(source, "java plugin", "java"),
        _ref(source, "mainClass", main_class),
    ])
    _set_compiled_artifact(
        intelligence, component,
        path=f"build/libs/{filename}",
        packaging="jar",
        launch_command=["java", "-jar", f"build/libs/{filename}"],
        rule_id=GRADLE_ARTIFACT_RULE,
        source_file=source,
        derived_from=refs,
    )
    wrapper = any(
        str(item.relative_path if hasattr(item, "relative_path") else item.get("relative_path")) == "gradlew"
        for item in intelligence.files
    )
    command = "./gradlew bootJar" if wrapper else "gradle bootJar"
    intelligence.commands.append({"name": "build", "command": command, "source_file": source, "confidence": "high"})
    intelligence.evidence.append(_evidence(
        source_file=source, key=f"{component.get('name')}.build_command",
        value=command, rule_id="gradle.bootJar.lifecycle.v1",
        derived_from=[_ref(source, "spring-boot plugin", "bootJar")],
    ))


def _derive_go(
    intelligence: ProjectIntelligence,
    component: dict[str, Any],
    metadata: list[dict[str, Any]],
) -> None:
    if len(metadata) != 1:
        _unsupported(intelligence, component, "Go module metadata is ambiguous", source_file="go.mod")
        return
    builds = [
        item for item in intelligence.commands
        if item.get("name") == "build"
        and _belongs(str(item.get("source_file") or ""), component)
        and re.search(r"""\bgo\s+build\b""", str(item.get("command") or ""))
    ]
    if len(builds) != 1:
        _unsupported(intelligence, component, "Go executable output is not explicitly configured with one go build -o command", source_file=str(metadata[0].get("source_file") or "go.mod"))
        return
    match = re.search(r"""(?:^|\s)-o\s+([^\s]+)""", str(builds[0].get("command") or ""))
    if not match or match.group(1).startswith("/") or ".." in match.group(1).split("/"):
        _unsupported(intelligence, component, "Go build output path is missing or unsafe", source_file=str(builds[0].get("source_file") or "Makefile"))
        return
    output = match.group(1).strip()
    entrypoints = [
        item for item in intelligence.entrypoints
        if _belongs(str(item.get("source_file") or ""), component)
        and item.get("kind") == "go_main_package"
    ]
    if len(entrypoints) != 1:
        _unsupported(intelligence, component, "Go main package is not uniquely proven", source_file=str(metadata[0].get("source_file") or "go.mod"))
        return
    source = str(metadata[0].get("source_file") or "go.mod")
    refs = [_ref(source, "module"), _ref(str(builds[0].get("source_file") or "Makefile"), "go build -o", output), _ref(str(entrypoints[0].get("source_file")), "go_main_package")]
    launch = output if output.startswith("./") else f"./{output}"
    _set_compiled_artifact(
        intelligence, component, path=output, packaging="go-binary",
        launch_command=[launch], rule_id=GO_ARTIFACT_RULE,
        source_file=source, derived_from=refs,
    )


def _derive_rust(
    intelligence: ProjectIntelligence,
    component: dict[str, Any],
    metadata: list[dict[str, Any]],
) -> None:
    if len(metadata) != 1:
        _unsupported(intelligence, component, "Rust Cargo metadata is ambiguous", source_file="Cargo.toml")
        return
    cargo = metadata[0]
    binaries = [str(item).strip() for item in cargo.get("binaries") or [] if str(item).strip()]
    package = str(cargo.get("package_name") or "").strip()
    if cargo.get("workspace") or len(binaries) > 1 or not (binaries or package):
        _unsupported(intelligence, component, "Rust workspace or multiple binary targets prevent exact executable selection", source_file=str(cargo.get("source_file") or "Cargo.toml"))
        return
    binary = binaries[0] if binaries else package
    main_files = [
        item for item in intelligence.entrypoints
        if _belongs(str(item.get("source_file") or ""), component)
        and item.get("kind") == "rust_main_function"
    ]
    if len(main_files) != 1:
        _unsupported(intelligence, component, "Rust main function is not uniquely proven", source_file=str(cargo.get("source_file") or "Cargo.toml"))
        return
    source = str(cargo.get("source_file") or "Cargo.toml")
    refs = [_ref(source, "package.name", package), _ref(source, "[[bin]].name", binary), _ref(str(main_files[0].get("source_file")), "rust_main_function")]
    _set_compiled_artifact(
        intelligence, component, path=f"target/release/{binary}",
        packaging="rust-binary", launch_command=[f"./target/release/{binary}"],
        rule_id=RUST_ARTIFACT_RULE, source_file=source, derived_from=refs,
    )
    command = "cargo build --release"
    intelligence.commands.append({"name": "build", "command": command, "source_file": source, "confidence": "high"})


def derive_deterministic_evidence(intelligence: ProjectIntelligence) -> ProjectIntelligence:
    """Add only facts proven by extracted build metadata and source facts."""

    parent_by_source = {
        str(item.get("source_file")): item
        for item in intelligence.build_metadata
        if item.get("source_file")
    }
    for item in intelligence.build_metadata:
        item["pom_count"] = len(intelligence.build_metadata)
    for component in intelligence.components:
        manager = component.get("package_manager")
        metadata = _metadata_for(component, intelligence.build_metadata)
        if manager == "maven":
            _derive_maven(intelligence, component, metadata, parent_by_source)
        elif manager == "gradle":
            _derive_gradle(intelligence, component, metadata)
        elif manager == "go":
            _derive_go(intelligence, component, metadata)
        elif manager == "cargo":
            _derive_rust(intelligence, component, metadata)
    return intelligence
