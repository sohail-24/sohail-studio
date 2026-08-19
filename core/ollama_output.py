"""Incremental cleanup for output from the interactive Ollama CLI.

The shell PTY is intentionally not processed by this module.  Ollama's
interactive terminal emits ANSI redraws, prompts, and input echo around the
model text; this processor keeps a terminal-readable stream and a clean
assistant-response stream from the same raw chunks.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass


RESPONSE_START = "\x00SOHAIL_OLLAMA_RESPONSE_START\x00"


@dataclass(frozen=True)
class ProcessedOllamaOutput:
    """A coalesced output event derived from one or more raw PTY chunks."""

    message: str
    terminal: str
    raw: str


class _AnsiStream:
    """Strip ANSI/control sequences without losing state across chunks."""

    def __init__(self) -> None:
        self._state = "text"
        self._csi_params = ""
        self._string_escape = False

    def feed(self, value: str) -> str:
        output: list[str] = []
        for char in value:
            code = ord(char)
            if self._state == "text":
                if char == "\x1b":
                    self._state = "escape"
                elif char in "\r\n\t\b":
                    output.append(char)
                elif code >= 0x20 and code != 0x7F:
                    output.append(char)
                continue

            if self._state == "escape":
                if char == "[":
                    self._state = "csi"
                    self._csi_params = ""
                elif char == "]":
                    self._state = "string"
                    self._string_escape = False
                elif char in "P^_":
                    self._state = "string"
                    self._string_escape = False
                else:
                    self._state = "text"
                continue

            if self._state == "csi":
                if 0x40 <= code <= 0x7E:
                    if char == "K" and self._csi_params.startswith("2"):
                        # Ollama clears the input line immediately before the
                        # model answer.  This marker is internal and never
                        # reaches the dashboard.
                        output.append(RESPONSE_START)
                    self._state = "text"
                    self._csi_params = ""
                elif 0x30 <= code <= 0x3F or 0x20 <= code <= 0x2F:
                    self._csi_params += char
                else:
                    self._state = "text"
                    self._csi_params = ""
                continue

            # OSC/DCS strings terminate at BEL or ST (ESC followed by '\\').
            if self._state == "string":
                if char == "\x07":
                    self._state = "text"
                elif self._string_escape:
                    self._state = "text" if char == "\\" else "string"
                    self._string_escape = False
                elif char == "\x1b":
                    self._string_escape = True

        return "".join(output)

    def flush(self) -> None:
        # An incomplete escape sequence is terminal metadata, never user text.
        self._state = "text"
        self._csi_params = ""
        self._string_escape = False


def normalize_terminal_text(value: str) -> str:
    """Apply basic terminal line discipline after ANSI has been removed."""

    value = value.replace(RESPONSE_START, "")
    lines: list[str] = []
    current: list[str] = []
    for char in value:
        if char == "\r":
            current.clear()
        elif char == "\b":
            if current:
                current.pop()
        elif char == "\n":
            lines.append("".join(current))
            current.clear()
        else:
            current.append(char)
    if current:
        lines.append("".join(current))
    result = "\n".join(lines)
    if value.endswith("\n"):
        result += "\n"
    return result


class OllamaOutputProcessor:
    """Convert raw Ollama PTY chunks into clean, coalesced output."""

    _prompt_prefix = ">>>"
    _thinking_line = re.compile(r"^\s*Thinking(?:\.{3}|…)?\s*$", re.IGNORECASE)

    def __init__(self, *, coalesce_ms: int = 50) -> None:
        self._ansi = _AnsiStream()
        self._coalesce_seconds = max(coalesce_ms, 1) / 1000
        self._pending_message = ""
        self._pending_terminal = ""
        self._pending_raw = ""
        self._last_emit = 0.0
        self._turn_active = False
        self._response_started = False
        self._prompt_tail = ""
        self._expected_input = ""
        self._in_think_tag = False
        self._think_tail = ""

    def note_input(self, value: str) -> None:
        """Start a new turn and suppress the terminal's echo of the input."""

        self._turn_active = True
        self._response_started = False
        self._prompt_tail = ""
        self._expected_input = normalize_terminal_text(value).strip()
        self._in_think_tag = False
        self._think_tail = ""

    def feed(self, raw: str, *, now: float | None = None) -> ProcessedOllamaOutput | None:
        """Process one raw chunk, preserving state across chunk boundaries."""

        if not raw:
            return None
        parsed = self._ansi.feed(raw)
        terminal = normalize_terminal_text(parsed)
        message = self._message_text(parsed)
        self._pending_terminal += terminal
        self._pending_message += message
        self._pending_raw += raw

        current_time = time.monotonic() if now is None else now
        should_emit = bool(self._pending_terminal or self._pending_message) and (
            current_time - self._last_emit >= self._coalesce_seconds
            or "\n" in message
            or len(self._pending_message) >= 160
        )
        if not should_emit:
            return None
        return self._emit(current_time)

    def flush(self, *, now: float | None = None) -> ProcessedOllamaOutput | None:
        """Flush buffered clean output at the end of a response/session."""

        self._ansi.flush()
        if self._think_tail:
            self._pending_message += self._think_tail
            self._think_tail = ""
        message = self._pending_message.strip()
        terminal = self._pending_terminal.rstrip()
        raw = self._pending_raw
        self._pending_message = ""
        self._pending_terminal = ""
        self._pending_raw = ""
        if not message and not terminal:
            return None
        self._last_emit = time.monotonic() if now is None else now
        return ProcessedOllamaOutput(message, terminal, raw)

    def _emit(self, now: float) -> ProcessedOllamaOutput:
        result = ProcessedOllamaOutput(
            self._pending_message,
            self._pending_terminal,
            self._pending_raw,
        )
        self._pending_message = ""
        self._pending_terminal = ""
        self._pending_raw = ""
        self._last_emit = now
        return result

    def _message_text(self, parsed: str) -> str:
        marker_index = parsed.find(RESPONSE_START)
        if marker_index >= 0:
            if not self._turn_active:
                return ""
            after_marker = parsed[marker_index + len(RESPONSE_START) :]
            # A fast first message can race the initial prompt.  Ollama uses
            # the same erase-line sequence before that prompt, so do not
            # treat startup UI as the answer boundary.
            if ">>>" in after_marker or "Send a message (/? for help)" in after_marker:
                return ""
            self._response_started = True
            parsed = after_marker
        elif not self._response_started:
            return ""

        parsed = parsed.replace(RESPONSE_START, "")
        parsed = self._remove_prompts(parsed)
        if not parsed:
            return ""
        return self._remove_thinking(parsed)

    def _remove_prompts(self, value: str) -> str:
        value = self._prompt_tail + value
        self._prompt_tail = ""
        while True:
            index = value.find(self._prompt_prefix)
            if index < 0:
                # Retain a possible split prompt prefix across PTY chunks.
                for size in (2, 1):
                    if value.endswith(">" * size):
                        self._prompt_tail = value[-size:]
                        return value[:-size]
                return value
            prefix = value[:index]
            remainder = value[index:]
            newline = remainder.find("\n")
            if newline < 0:
                self._prompt_tail = remainder
                return prefix
            value = prefix + remainder[newline + 1 :]

    def _remove_thinking(self, value: str) -> str:
        value = self._think_tail + value
        self._think_tail = ""
        output: list[str] = []
        while value:
            if self._in_think_tag:
                end = value.find("</think>")
                if end < 0:
                    self._think_tail = value[-8:]
                    return "".join(output)
                value = value[end + len("</think>") :]
                self._in_think_tag = False
                continue

            start = value.find("<think>")
            if start >= 0:
                output.append(value[:start])
                value = value[start + len("<think>") :]
                self._in_think_tag = True
                continue

            # Remove only a standalone visible status line.  Ordinary prose
            # containing the word "thinking" is left untouched.
            lines = value.splitlines(keepends=True)
            if lines and not lines[-1].endswith(("\n", "\r")):
                candidate = lines.pop()
                if not self._thinking_line.match(candidate):
                    output.append(candidate)
            for line in lines:
                if not self._thinking_line.match(line.rstrip("\r\n")):
                    output.append(line)
            return "".join(output)
        return "".join(output)
