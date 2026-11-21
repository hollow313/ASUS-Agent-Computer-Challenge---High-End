"""The agent loop: objective → plan → tool → observation → … → deliverable."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .planners import Planner
from .skills import SkillStore
from .tools import Sandbox, ToolError, NetworkPolicy, build_registry

APPROVAL_TOOLS = ("fs_write", "fs_move", "mail_move", "run")


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
    scenario: str = ""
    network: dict[str, Any] = field(default_factory=lambda: {"network_mode": "deny"})
    events: list[dict[str, Any]] = field(default_factory=list)

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
            "scenario": self.scenario,
            "network": self.network,
            "events": list(self.events),
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
        network_config: dict[str, Any] | None = None,
        runner: Any = None,
        approver: Callable[[str, dict[str, Any]], bool] | None = None,
        scenario: str = "",
    ) -> None:
        self.planner = planner
        self.workspace = Path(workspace)
        self.sandbox = Sandbox(workspace)
        self.runs_dir = Path(runs_dir)
        self.max_steps = max_steps
        self.on_step = on_step
        self.skills = skills
        self.children_dir = children_dir
        self.delegation_depth = delegation_depth
        self.settings = settings
        self.network_config = network_config or {"mode": "deny"}
        self.runner = runner
        self.approver = approver
        self.scenario = scenario

    def run(self, objective: str, run_id: str | None = None) -> RunResult:
        run_id = run_id or uuid.uuid4().hex[:10]
        result = RunResult(
            run_id=run_id,
            objective=objective,
            status="running",
            workspace=str(self.sandbox.root),
            planner=getattr(self.planner, "label", "unknown"),
            scenario=self.scenario,
        )
        artifacts: list[str] = []
        network = NetworkPolicy(self.network_config, result.events)
        result.network = network.as_dict()
        tools = build_registry(
            self.sandbox,
            artifacts,
            self.skills,
            self.children_dir,
            self.runs_dir,
            parent_planner=self.planner,
            depth=self.delegation_depth,
            settings=self.settings,
            network=network,
            runner=self.runner,
            events=result.events,
        )
        # le planner réel reçoit le catalogue de ce run (et non celui du parent)
        if hasattr(self.planner, "tools") and not getattr(self.planner, "tools", None):
            self.planner.tools = tools
        history: list[dict[str, Any]] = []
        repeats: dict[str, int] = {}
        nudges = 0  # relances « tu n'as pas écrit le livrable », avant de bloquer  # anti-boucle : mêmes arguments, même erreur

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
                expected = _expected_deliverable(objective)
                produced = sorted(
                    str(p.relative_to(self.workspace))
                    for p in self.workspace.rglob("*")
                    if p.is_file() and p.name not in {"cassette.json"} and p.suffix in {".md", ".txt", ".json", ".csv", ".svg"}
                )
                if expected and not any(name.endswith(expected) for name in produced) and nudges < 2:
                    nudges += 1
                    message = (
                        f"Tu as répondu final, mais {expected} n'existe pas dans le bac à sable. "
                        f"Écris-le maintenant avec fs_write, puis réponds final. "
                        f"Fichiers présents : {', '.join(produced) or 'aucun'}."
                    )
                    step = Step(index, thought or "Le modèle a conclu trop tôt.", None, {}, message, _ms(started), True)
                    result.steps.append(step)
                    _notify(self.on_step, step)
                    history.append({"thought": thought, "tool": None, "args": {}, "observation": message})
                    continue
                if expected and not any(name.endswith(expected) for name in produced):
                    step = Step(
                        index,
                        thought or "Le modèle a conclu.",
                        None,
                        {},
                        f"aucun livrable : {expected} n'a été écrit",
                        _ms(started),
                        True,
                    )
                    result.steps.append(step)
                    _notify(self.on_step, step)
                    result.status = "blocked"
                    result.summary = (
                        f"bloqué : le modèle a conclu sans écrire {expected}. "
                        f"Fichiers présents : {', '.join(produced) or 'aucun'}."
                    )
                    break
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
            elif self.approver is not None and tool_name in APPROVAL_TOOLS and not self.approver(tool_name, args):
                observation, error = f"refusé par l'opérateur : {tool_name}", True
                result.events.append(
                    {"event": "approval", "tool": tool_name, "args": args, "decision": "refused"}
                )
            else:
                if self.approver is not None and tool_name in APPROVAL_TOOLS:
                    result.events.append(
                        {"event": "approval", "tool": tool_name, "args": args, "decision": "approved"}
                    )
                try:
                    observation = tools[tool_name].fn(**args)
                    error = False
                except ToolError as exc:
                    observation, error = str(exc), True
                except TypeError as exc:
                    observation, error = f"arguments invalides pour {tool_name} : {exc}", True
                except Exception as exc:  # un outil qui plante ne doit pas emporter le run
                    observation, error = f"échec interne de {tool_name} : {type(exc).__name__}: {exc}"[:400], True
            observation = observation if isinstance(observation, str) else json.dumps(observation, ensure_ascii=False)

            step = Step(index, thought, tool_name, args, observation, _ms(started), error)
            result.steps.append(step)

            signature = json.dumps([tool_name, args], ensure_ascii=False, sort_keys=True)
            repeats[signature] = repeats.get(signature, 0) + 1
            if repeats[signature] == 2 and not error:
                # petit coup de coude avant de bloquer : le modèle tourne en rond sur un résultat connu
                observation = (
                    f"[relance] même appel que l'étape précédente, résultat identique. "
                    f"Avance : écris le livrable ou conclus.\n{observation}"
                )
                step.observation = observation
            limite = 3 if error else 4
            if repeats[signature] >= limite:
                # insister ne sert à rien : même appel répété, on s'arrête net
                dead = Step(
                    index,
                    f"{repeats[signature]} appels identiques à {tool_name}, sans progrès.",
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
                    f"Bloqué : {tool_name} a été appelé {repeats[signature]} fois avec les mêmes "
                    f"arguments{', en échec' if error else ', sans avancer'}. "
                    "Le budget restant n'a pas été gaspillé."
                )
                break
            history.append(
                {"thought": thought, "tool": tool_name, "args": args, "observation": observation}
            )
            _notify(self.on_step, step)
        else:
            result.status = "budget"
            result.summary = f"Budget de {self.max_steps} étapes atteint sans conclusion."

        for event in result.events:
            event.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
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


def _expected_deliverable(objective: str) -> str:
    """Nom de fichier attendu, lu dans l'objectif (« écris briefing.md »)."""
    matches = re.findall(r"[\w-]+\.(?:md|txt|csv|json|svg)\b", objective or "")
    return matches[-1] if matches else ""
