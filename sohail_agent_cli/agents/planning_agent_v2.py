"""PlanningAgent V2 implementation backed by the Engineering Decision Engine."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
from sohail_agent_cli.generators import PlanningGenerator
from sohail_agent_cli.planning.decision_engine import EngineeringDecisionEngine, PlanningSelections
from sohail_agent_cli.planning.questions import build_planning_context, infer_project_category


class PlanningAgentV2(BaseAgent):
    """Create planning packages from explicit Engineering Decision Engine choices."""

    SUMMARY_FILENAMES = {"TASK.md", "ARCHITECTURE.md", "REQUIREMENTS.md"}
    SELECTIONS_FILENAME = "planning-selections.json"

    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
        engine: EngineeringDecisionEngine | None = None,
    ) -> None:
        super().__init__(
            name="planning_agent_v2",
            description="Creates planning packages from explicit engineering decisions",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.engine = engine or EngineeringDecisionEngine()
        self.generator = PlanningGenerator()

    async def execute(
        self,
        path: Path,
        goal: str | None = None,
        project_name: str | None = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> AgentResult:
        """Run the PlanningAgent V2 workflow."""
        try:
            raw_output_path = Path(path)
            if ".." in raw_output_path.parts:
                return AgentResult.failure("Output path cannot contain parent traversal ('..')")

            output_root = raw_output_path.expanduser().resolve()
            if output_root.exists() and not output_root.is_dir():
                return AgentResult.failure(f"Output path is not a directory: {output_root}")

            selections = self.engine.run(
                initial_answers=self._initial_answers(goal, project_name)
            )
            context = self._build_context(selections)
            generated = self._with_selection_artifact(
                self.generator.generate(context),
                selections,
            )
            targets = self._resolve_targets(output_root, generated)
            conflicts = self._preflight_conflicts(targets, overwrite)
            if conflicts:
                for conflict in conflicts:
                    self.error(conflict)
                return AgentResult.failure(
                    "Planning package was not written because output conflicts were found",
                    error="; ".join(conflicts),
                )

            if self.dry_run:
                dry_run_files = []
                for _relative_path, target_path, _content in targets:
                    action = "overwrite" if target_path.exists() else "create"
                    self.info(f"[DRY RUN] Would {action} {target_path}")
                    dry_run_files.append(str(target_path))
                return AgentResult.success(
                    "Dry run complete; no files were modified",
                    data={
                        "dry_run": True,
                        "dry_run_files": dry_run_files,
                        "output_path": str(output_root),
                        "custom_requirements": len(selections.custom_requirements),
                    },
                )

            created: list[Path] = []
            overwritten: list[Path] = []
            failed: list[Path] = []
            for relative_path, target_path, content in targets:
                existed = target_path.exists()
                allow_overwrite = overwrite and self._can_overwrite(relative_path)
                success, message, is_dry_run = await self.write_file(
                    target_path,
                    content,
                    overwrite=allow_overwrite,
                )
                if not success or is_dry_run:
                    failed.append(target_path)
                    self.error(message)
                    return AgentResult(
                        success=False,
                        message="Planning package is incomplete because a file write failed",
                        error=message,
                        files_created=created,
                        files_skipped=failed,
                        data={
                            "created_files": [str(item) for item in created],
                            "overwritten_files": [str(item) for item in overwritten],
                            "failed_files": [str(item) for item in failed],
                            "output_path": str(output_root),
                        },
                    )
                if existed:
                    overwritten.append(target_path)
                else:
                    created.append(target_path)
                self.success(message)

            return AgentResult.success(
                f"Planning package created at {output_root}",
                files_created=created + overwritten,
                data={
                    "created_files": [str(item) for item in created],
                    "overwritten_files": [str(item) for item in overwritten],
                    "failed_files": [],
                    "output_path": str(output_root),
                    "requirements": len(context.requirements),
                    "tasks": len(context.tasks),
                    "decisions": len(context.decisions),
                    "open_questions": len(context.open_questions),
                    "custom_requirements": len(selections.custom_requirements),
                    "selections_file": str(output_root / self.SELECTIONS_FILENAME),
                },
            )
        except ValueError as exc:
            self.error(str(exc))
            return AgentResult.failure("Planning validation failed", error=str(exc))
        except (EOFError, KeyboardInterrupt):
            self.warning("Planning cancelled; no files changed")
            return AgentResult.success(
                "Planning cancelled; no files changed",
                data={"cancelled": True},
            )
        except Exception as exc:
            if self.verbose:
                self.error(f"Unexpected PlanningAgent V2 error: {exc}")
            else:
                self.error("Unexpected PlanningAgent V2 error; rerun with --verbose")
            return AgentResult.failure("Planning failed", error=str(exc))

    def _build_context(self, selections: PlanningSelections):
        goal = self._text(selections.get("project.goal"))
        project_name = self._text(selections.get("project.name"))
        category = self._text(selections.get("project.project_type"))
        if not category:
            category = infer_project_category(goal)

        answers = {
            "target_users": self._text(selections.get("project.target_users")),
            "first_release_scope": self._text(
                selections.get("features.first_release_scope")
            ),
            "out_of_scope": self._text(selections.get("features.out_of_scope")),
            "frontend": self._text(
                selections.get("frontend.framework"),
                fallback="undecided",
            ),
            "backend": self._text(
                selections.get("backend.framework"),
                fallback="undecided",
            ),
            "database": self._text(
                selections.get("database.primary_database"),
                fallback="undecided",
            ),
            "authentication": self._text(
                selections.get("authentication.approach"),
                fallback="undecided",
            ),
            "docker": self._yes_no(selections.get("container.docker_required")),
            "kubernetes": self._text(
                selections.get("container.kubernetes"),
                fallback="undecided",
            ),
            "deployment_target": self._text(
                selections.get("infrastructure.deployment_target")
            ),
            "quality_requirements": self._quality_requirements(selections),
        }
        return build_planning_context(
            goal=goal,
            project_name=project_name,
            category=category,
            answers=answers,
        )

    def _with_selection_artifact(
        self,
        generated: OrderedDict[Path, str],
        selections: PlanningSelections,
    ) -> OrderedDict[Path, str]:
        files: OrderedDict[Path, str] = OrderedDict()
        files[Path(self.SELECTIONS_FILENAME)] = selections.to_json()
        files.update(generated)
        return files

    def _initial_answers(
        self,
        goal: str | None,
        project_name: str | None,
    ) -> dict[str, str]:
        answers: dict[str, str] = {}
        if goal and goal.strip():
            answers["project.goal"] = goal.strip()
            answers["project.project_type"] = infer_project_category(goal)
        if project_name and project_name.strip():
            answers["project.name"] = project_name.strip()
        return answers

    def _quality_requirements(self, selections: PlanningSelections) -> str:
        items: list[str] = []
        if selections.get("monitoring.enabled") is True:
            items.append("monitoring")
        security = self._text(selections.get("security.baseline"))
        if security and security != "undecided":
            items.append(f"{security} security")
        testing = selections.get("testing.strategy", ())
        if isinstance(testing, list | tuple):
            items.extend(f"{item} testing" for item in testing)
        documentation = self._text(selections.get("documentation.level"))
        if documentation:
            items.append(f"{documentation} documentation")
        return ", ".join(dict.fromkeys(items))

    @staticmethod
    def _text(value: Any, fallback: str = "") -> str:
        if value is None:
            return fallback
        if isinstance(value, list | tuple):
            text = ", ".join(str(item).strip() for item in value if str(item).strip())
            return text or fallback
        text = str(value).strip()
        return text or fallback

    @staticmethod
    def _yes_no(value: Any) -> str:
        if value is True:
            return "yes"
        if value is False:
            return "no"
        return "undecided"

    @classmethod
    def _can_overwrite(cls, relative_path: Path) -> bool:
        return relative_path.name in cls.SUMMARY_FILENAMES | {cls.SELECTIONS_FILENAME}

    @staticmethod
    def _resolve_targets(
        output_root: Path,
        generated: OrderedDict[Path, str],
    ) -> list[tuple[Path, Path, str]]:
        targets: list[tuple[Path, Path, str]] = []
        for relative_path, content in generated.items():
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError(f"Unsafe generated path: {relative_path}")
            target_path = (output_root / relative_path).resolve()
            if not target_path.is_relative_to(output_root):
                raise ValueError(f"Generated path escapes output directory: {relative_path}")
            targets.append((relative_path, target_path, content))
        return targets

    def _preflight_conflicts(
        self,
        targets: list[tuple[Path, Path, str]],
        overwrite: bool,
    ) -> list[str]:
        conflicts: list[str] = []
        for relative_path, target_path, _content in targets:
            if not target_path.exists():
                continue
            if relative_path.parts[0] == "decisions":
                conflicts.append(f"Decision record already exists and is protected: {target_path}")
            elif not overwrite or not self._can_overwrite(relative_path):
                conflicts.append(f"File exists (use --overwrite): {target_path}")
        return conflicts
