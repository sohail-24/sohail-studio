"""Interactive PlanningAgent V1 implementation."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
from sohail_agent_cli.generators import PlanningGenerator
from sohail_agent_cli.planning.questions import (
    QUESTION_CATALOG,
    PlanningQuestion,
    build_planning_context,
    infer_project_category,
    infer_project_name,
)

PromptCallable = Callable[[str], str]
ConfirmCallable = Callable[[str], bool]


class PlanningAgent(BaseAgent):
    """Gather confirmed project choices and write persistent planning documents."""

    SUMMARY_FILENAMES = {"TASK.md", "ARCHITECTURE.md", "REQUIREMENTS.md"}

    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
        prompt: PromptCallable | None = None,
        confirm: ConfirmCallable | None = None,
    ) -> None:
        super().__init__(
            name="planning_agent",
            description="Creates requirements, architecture, tasks, and decision records",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.generator = PlanningGenerator()
        self._prompt = prompt or input
        self._confirm = confirm or self._default_confirm
        self._uses_default_prompt = prompt is None

    async def execute(
        self,
        path: Path,
        goal: str,
        project_name: str | None = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> AgentResult:
        """Run the complete PlanningAgent V1 creation workflow."""
        try:
            goal = goal.strip()
            if not goal:
                return AgentResult.failure("Project goal cannot be empty")

            raw_output_path = Path(path)
            if ".." in raw_output_path.parts:
                return AgentResult.failure("Output path cannot contain parent traversal ('..')")
            output_root = raw_output_path.expanduser().resolve()
            if output_root.exists() and not output_root.is_dir():
                return AgentResult.failure(f"Output path is not a directory: {output_root}")
            if self._uses_default_prompt and not sys.stdin.isatty():
                return AgentResult.failure(
                    "PlanningAgent V1 requires an interactive terminal for clarification questions"
                )

            category = infer_project_category(goal)
            suggested_name = project_name or infer_project_name(goal)
            answers = self._collect_answers(category, suggested_name)
            confirmed_name = answers.pop("project_name")
            context = build_planning_context(
                goal=goal,
                project_name=confirmed_name,
                category=category,
                answers=answers,
            )
            self._print_confirmation_summary(context, output_root, overwrite)
            if not self._confirm("Create this planning package? [y/N]: "):
                self.info("Planning cancelled; no files changed")
                return AgentResult.success(
                    "Planning cancelled; no files changed",
                    data={"cancelled": True, "output_path": str(output_root)},
                )

            generated = self.generator.generate(context)
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
                        "requirements": len(context.requirements),
                        "tasks": len(context.tasks),
                        "decisions": len(context.decisions),
                    },
                )

            created: list[Path] = []
            overwritten: list[Path] = []
            failed: list[Path] = []
            for relative_path, target_path, content in targets:
                existed = target_path.exists()
                allow_overwrite = overwrite and relative_path.name in self.SUMMARY_FILENAMES
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
                },
            )
        except (EOFError, KeyboardInterrupt):
            self.warning("Planning cancelled; no files changed")
            return AgentResult.success(
                "Planning cancelled; no files changed",
                data={"cancelled": True},
            )
        except ValueError as exc:
            self.error(str(exc))
            return AgentResult.failure("Planning validation failed", error=str(exc))
        except Exception as exc:
            if self.verbose:
                self.error(f"Unexpected planning error: {exc}")
            else:
                self.error("Unexpected planning error; rerun with --verbose for details")
            return AgentResult.failure("Planning failed", error=str(exc))

    def _collect_answers(
        self,
        category: str,
        suggested_name: str,
    ) -> dict[str, str]:
        answers: dict[str, str] = {}
        for question in QUESTION_CATALOG:
            if not question.applies(category, answers):
                continue
            default = suggested_name if question.destination == "project_name" else ""
            answers[question.destination] = self._ask_question(question, default)
        return answers

    def _ask_question(self, question: PlanningQuestion, default: str = "") -> str:
        options = f" [{'/'.join(question.options)}]" if question.options else ""
        default_text = f" (default: {default})" if default else ""
        optional_text = " (optional; press Enter to skip)" if not question.required else ""
        prompt_text = (
            f"{question.question_id} — {question.prompt}{options}{default_text}{optional_text}: "
        )
        while True:
            answer = self._prompt(prompt_text)
            if not answer.strip() and default:
                answer = default
            try:
                return question.validate_answer(answer)
            except ValueError as exc:
                self.warning(str(exc))

    @staticmethod
    def _default_confirm(prompt_text: str) -> bool:
        return input(prompt_text).strip().lower() in {"y", "yes"}

    def _print_confirmation_summary(
        self,
        context: Any,
        output_root: Path,
        overwrite: bool,
    ) -> None:
        self.info(f"Project: {context.brief.name}")
        self.info(f"Goal: {context.brief.goal}")
        self.info(f"Requirements: {len(context.requirements)}")
        self.info(f"Tasks: {len(context.tasks)}")
        self.info(f"Accepted decisions: {len(context.decisions)}")
        self.info(f"Open questions: {len(context.open_questions)}")
        self.info(f"Output: {output_root}")
        if context.decisions:
            self.info(
                "Decisions: "
                + ", ".join(
                    f"{decision.topic}={decision.choice}" for decision in context.decisions
                )
            )
        if context.open_questions:
            self.warning(
                "Unresolved: "
                + "; ".join(question.text for question in context.open_questions)
            )
        if overwrite:
            self.warning(
                "--overwrite may replace TASK.md, ARCHITECTURE.md, and REQUIREMENTS.md; "
                "decision records are always protected"
            )

    @staticmethod
    def _resolve_targets(
        output_root: Path,
        generated: dict[Path, str],
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
            elif not overwrite:
                conflicts.append(f"File exists (use --overwrite): {target_path}")
        return conflicts
