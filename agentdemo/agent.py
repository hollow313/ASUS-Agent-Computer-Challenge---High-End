"""The agent loop: objective → plan → tool → observation → … → deliverable."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .planners import Planner
from .tools import Sandbox, ToolError, build_registry


@dataclass
class Step:
    index: int
    thought: str
    tool: str | None
    args: dict[str, Any]
    observation: str
    duration_ms: int
    error: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "thought": self.thought,
            "tool": self.tool,
            "args": self.args,
            "observation": self.observation,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class RunResult:
    run_id: str
    objective: str
    status: str
    steps: list[Step] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    summary: str = ""
    workspace: str = ""
    planner: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "status": self.status,
            "steps": [step.as_dict() for step in self.steps],
            "artifacts": list(self.artifacts),
            "summary": self.summary,
            "workspace": self.workspace,
            "planner": self.planner,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round((self.finished_at or time.time()) - self.started_at, 2),
        }


class Agent:
    """Minimal but honest agentic loop, with a hard step budget."""

    def __init__(
        self,
        planner: Planner,
        workspace: Path,
        runs_dir: Path,
        max_steps: int = 14,
        on_step: Callable[[Step], None] | None = None,
    ) -> None:
        self.planner = planner
        self.sandbox = Sandbox(workspace)
        self.runs_dir = Path(runs_dir)
        self.max_steps = max_steps
        self.on_step = on_step

    def run(self, objective: str, run_id: str | None = None) -> RunResult:
        run_id = run_id or uuid.uuid4().hex[:10]
        result = RunResult(
            run_id=run_id,
            objective=objective,
            status="running",
            workspace=str(self.sandbox.root),
            planner=getattr(self.planner, "label", "unknown"),
        )
        artifacts: list[str] = []
        tools = build_registry(self.sandbox, artifacts)
        history: list[dict[str, Any]] = []

        for index in range(1, self.max_steps + 1):
            started = time.perf_counter()
            try:
                action = self.planner.next_action(objective, history)
            except RuntimeError as exc:
                step = Step(index, "Le modèle n'a pas répondu.", None, {}, str(exc), _ms(started), True)
                result.steps.append(step)
                result.status = "failed"
                result.summary = str(exc)
                break

            thought = str(action.get("thought", "")).strip()
            if action.get("final"):
                result.summary = str(action["final"]).strip()
                step = Step(index, thought or "Objectif atteint.", None, {}, "run terminé", _ms(started))
                result.steps.append(step)
                _notify(self.on_step, step)
                result.status = "done"
                break

            tool_name = str(action.get("tool", "")).strip()
            args = action.get("args") or {}
            if tool_name not in tools:
                observation, error = f"outil inconnu : {tool_name}", True
            else:
                try:
                    observation = tools[tool_name].fn(**args)
                    error = False
                except ToolError as exc:
                    observation, error = str(exc), True
                except TypeError as exc:
                    observation, error = f"arguments invalides pour {tool_name} : {exc}", True
            observation = observation if isinstance(observation, str) else json.dumps(observation, ensure_ascii=False)

            step = Step(index, thought, tool_name, args, observation, _ms(started), error)
            result.steps.append(step)
            history.append(
                {"thought": thought, "tool": tool_name, "args": args, "observation": observation}
            )
            _notify(self.on_step, step)
        else:
            result.status = "budget"
            result.summary = f"Budget de {self.max_steps} étapes atteint sans conclusion."

        result.artifacts = artifacts
        result.finished_at = time.time()
        self._write_log(result)
        return result

    def _write_log(self, result: RunResult) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.runs_dir / f"{result.run_id}.json"
        log_path.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _notify(callback: Callable[[Step], None] | None, step: Step) -> None:
    if callback is not None:
        callback(step)
