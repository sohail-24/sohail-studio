"""Terminal renderer for Engineering Decision Engine V1."""

from __future__ import annotations

from typing import Callable

from .models import Question, QuestionAnswer, QuestionGroup

PromptCallable = Callable[[str], str]
WriteCallable = Callable[[str], None]


class TerminalRenderer:
    """Minimal terminal renderer for EDE questions."""

    def __init__(
        self,
        prompt: PromptCallable | None = None,
        write: WriteCallable | None = None,
    ) -> None:
        self._prompt = prompt or input
        self._write = write or print

    def render_group(self, group: QuestionGroup) -> None:
        """Render a question group heading."""
        self._write("")
        self._write(f"## {group.title}")
        if group.description:
            self._write(group.description)

    def ask(self, question: Question) -> QuestionAnswer:
        """Ask one question and return a normalized answer."""
        if question.question_type == "single_choice":
            value = self._ask_single_choice(question)
        elif question.question_type == "multi_choice":
            value = self._ask_multi_choice(question)
        elif question.question_type == "boolean":
            value = self._ask_boolean(question)
        elif question.question_type == "number":
            value = self._ask_number(question)
        else:
            value = self._ask_text(question)
        return QuestionAnswer(
            question_id=question.question_id,
            key=question.key,
            value=value,
        )

    def _ask_text(self, question: Question) -> str:
        prompt_text = self._base_prompt(question)
        while True:
            raw = self._prompt(prompt_text)
            if not raw.strip() and question.default is not None:
                raw = str(question.default)
            value = raw.strip()
            if value or not question.required:
                return value
            self._write("An answer is required.")

    def _ask_number(self, question: Question) -> int | float | None:
        prompt_text = self._base_prompt(question)
        while True:
            raw = self._prompt(prompt_text).strip()
            if not raw and question.default is not None:
                raw = str(question.default)
            if not raw and not question.required:
                return None
            try:
                number = float(raw) if "." in raw else int(raw)
            except ValueError:
                self._write("Enter a valid number.")
                continue
            return number

    def _ask_boolean(self, question: Question) -> bool | None:
        default_hint = self._format_default(question.default)
        prompt_text = f"{question.prompt} [y/n]{default_hint}: "
        while True:
            raw = self._prompt(prompt_text).strip().lower()
            if not raw and question.default is not None:
                return bool(question.default)
            if raw in {"y", "yes", "true", "1"}:
                return True
            if raw in {"n", "no", "false", "0"}:
                return False
            if not raw and not question.required:
                return None
            self._write("Choose yes or no.")

    def _ask_single_choice(self, question: Question) -> str:
        self._render_options(question)
        prompt_text = self._choice_prompt(question, "Choose one")
        allowed_by_value = {option.value.lower(): option.value for option in question.options}
        allowed_by_label = {option.label.lower(): option.value for option in question.options}
        while True:
            raw = self._prompt(prompt_text).strip()
            if not raw and question.default is not None:
                return str(question.default)
            if raw.isdigit():
                index = int(raw)
                if 1 <= index <= len(question.options):
                    return question.options[index - 1].value
            lowered = raw.lower()
            if lowered in allowed_by_value:
                return allowed_by_value[lowered]
            if lowered in allowed_by_label:
                return allowed_by_label[lowered]
            self._write("Choose a valid option number or value.")

    def _ask_multi_choice(self, question: Question) -> tuple[str, ...]:
        self._render_options(question)
        prompt_text = self._choice_prompt(question, "Choose one or more")
        allowed_by_value = {option.value.lower(): option.value for option in question.options}
        allowed_by_label = {option.label.lower(): option.value for option in question.options}
        while True:
            raw = self._prompt(prompt_text).strip()
            if not raw and question.default is not None:
                return tuple(question.default)
            if not raw and not question.required:
                return ()

            selected: list[str] = []
            invalid = False
            for item in [part.strip() for part in raw.split(",") if part.strip()]:
                if item.isdigit():
                    index = int(item)
                    if 1 <= index <= len(question.options):
                        selected.append(question.options[index - 1].value)
                    else:
                        invalid = True
                elif item.lower() in allowed_by_value:
                    selected.append(allowed_by_value[item.lower()])
                elif item.lower() in allowed_by_label:
                    selected.append(allowed_by_label[item.lower()])
                else:
                    invalid = True
            deduped = tuple(dict.fromkeys(selected))
            if deduped and not invalid:
                return deduped
            if not deduped and not question.required and not invalid:
                return ()
            self._write("Choose valid option numbers or values separated by commas.")

    def _render_options(self, question: Question) -> None:
        self._write(question.prompt)
        for index, option in enumerate(question.options, start=1):
            detail = f" - {option.description}" if option.description else ""
            self._write(f"  {index}. {option.label}{detail}")

    def _base_prompt(self, question: Question) -> str:
        return f"{question.prompt}{self._format_default(question.default)}: "

    def _choice_prompt(self, question: Question, label: str) -> str:
        return f"{label}{self._format_default(question.default)}: "

    @staticmethod
    def _format_default(default: object) -> str:
        if default is None:
            return ""
        if isinstance(default, tuple):
            return f" (default: {', '.join(str(item) for item in default)})"
        return f" (default: {default})"
