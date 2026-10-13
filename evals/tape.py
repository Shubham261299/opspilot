"""Record and replay a language model's answers.

Why: CI has no model, and a fake that returns made-up answers would make a score meaningless.
So an eval is run once against the real model while a *tape* records every request and the
raw answer. Later runs (CI, or a quick local check) play the answers back from the tape, and
everything else (parsing, matching, arithmetic checks, scoring) runs for real.

A request is identified by a hash of its messages and the answer's JSON schema. Change a prompt
or a schema and the hash changes: the replay then says which request is missing and the tape
must be recorded again with the real model (`python evals/run.py <suite> --record`).

The tape wraps `litellm.acompletion`'s shape, one level below `complete_structured`, so the
real code around the model call (fence stripping, validation, the repair retry) is exercised too.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

Completion = Callable[..., Awaitable[Any]]


class ReplayMiss(Exception):
    """The tape has no answer for this request: a prompt or schema changed since recording."""


def request_key(messages: list[dict[str, str]], schema: Any) -> str:
    """A short, stable id for 'these messages, asking for this JSON shape'."""
    shape = schema.model_json_schema() if hasattr(schema, "model_json_schema") else None
    blob = json.dumps({"messages": messages, "schema": shape}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _purpose(kwargs: dict[str, Any]) -> str:
    return str((kwargs.get("metadata") or {}).get("generation_name", ""))


def _answer(content: str) -> Any:
    """The part of a LiteLLM response that complete_structured reads."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@dataclass
class Tape:
    """The recorded answers of one eval suite, saved as a JSON file."""

    path: Path
    model: str = ""
    recorded_at: str = ""
    entries: dict[str, dict[str, str]] = field(default_factory=dict)  # key -> purpose, answer
    expected_summary: dict[str, Any] = field(default_factory=dict)  # the score at record time

    @classmethod
    def load(cls, path: Path) -> "Tape":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path=path,
            model=data["model"],
            recorded_at=data["recorded_at"],
            entries=data["entries"],
            expected_summary=data["expected_summary"],
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "model": self.model,
            "recorded_at": self.recorded_at,
            "expected_summary": self.expected_summary,
            "entries": self.entries,
        }
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")


class RecordingCompletion:
    """Calls the real model and writes each answer on the tape."""

    def __init__(self, real: Completion, tape: Tape) -> None:
        self.real, self.tape = real, tape

    async def __call__(self, **kwargs: Any) -> Any:
        response = await self.real(**kwargs)
        content = response.choices[0].message.content
        key = request_key(kwargs["messages"], kwargs.get("response_format"))
        self.tape.entries[key] = {
            "purpose": _purpose(kwargs),
            "answer": content if isinstance(content, str) else "",
        }
        return response


class ReplayCompletion:
    """Plays the tape's answers back. Never reaches a model.

    `misses` lists requests the tape didn't have. complete_structured turns any error from the
    model into an LlmError (and the reader into an "unreadable" result), so a test must check
    `misses` is empty: otherwise a changed prompt would look like a bad score, not a stale tape.
    """

    def __init__(self, tape: Tape) -> None:
        self.tape = tape
        self.misses: list[str] = []

    async def __call__(self, **kwargs: Any) -> Any:
        key = request_key(kwargs["messages"], kwargs.get("response_format"))
        entry = self.tape.entries.get(key)
        if entry is None:
            self.misses.append(f"{_purpose(kwargs) or 'unknown'} ({key})")
            raise ReplayMiss(f"No recorded answer for request {key}; record the tape again.")
        return _answer(entry["answer"])
