"""The agent loop: objective → plan → tool → observation → … → deliverable."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .planners import Planner
from .skills import SkillStore
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
        skills: SkillStore | None = None,
        children_dir: "Path | None" = None,
        delegation_depth: int = 0,
        settings: Any = None,
    ) -> None:
        self.planner = planner
        self.sandbox = Sandbox(workspace)
        self.runs_dir = Path(runs_dir)
        self.max_steps = max_steps
        self.on_step = on_step
        self.skills = skills
        self.children_dir = children_dir
        self.delegation_depth = delegation_depth
        self.settings = settings

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
        tools = build_registry(
            self.sandbox,
            artifacts,
            self.skills,
            self.children_dir,
            self.runs_dir,
            parent_planner=self.planner,
            depth=self.delegation_depth,
            settings=self.settings,
        )
        # le planner réel reçoit le catalogue de ce run (et non celui du parent)
        if hasattr(self.planner, "tools") and not getattr(self.planner, "tools", None):
            self.planner.tools = tools
        history: list[dict[str, Any]] = []
        repeats: dict[str, int] = {}  # anti-boucle : mêmes arguments, même erreur

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
            if isinstance(args, str):
                # les petits modèles renvoient parfois les arguments en chaîne JSON
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
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

            if error:
                signature = json.dumps([tool_name, args], ensure_ascii=False, sort_keys=True)
                repeats[signature] = repeats.get(signature, 0) + 1
                if repeats[signature] >= 3:
                    # trois fois le même appel en échec : insister ne sert à rien, on s'arrête net
                    dead = Step(
                        index,
                        "Trois tentatives identiques, toutes en échec.",
                        None,
                        {},
                        "run interrompu pour éviter d'épuiser le budget",
                        _ms(started),
                        True,
                    )
                    result.steps.append(dead)
                    _notify(self.on_step, dead)
                    result.status = "blocked"
                    result.summary = (
                        f"Bloqué : {tool_name} a échoué trois fois avec les mêmes arguments "
                        f"({observation[:200]}). Le budget restant n'a pas été gaspillé."
                    )
                    break
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
