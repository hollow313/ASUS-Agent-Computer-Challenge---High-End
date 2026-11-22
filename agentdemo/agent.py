"""The agent loop: objective → plan → tool → observation → … → deliverable."""

from __future__ import annotations

import json
import os
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


class ResumeError(RuntimeError):
    """Reprise impossible, avec une raison lisible plutôt qu'une trace."""


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
        resume: Path | None = None,
        save_state: bool = False,
        reviewer: Any = None,
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
        self.resume = Path(resume) if resume else None
        self.save_state = save_state
        self.reviewer = reviewer

    def _state_path(self, run_id: str) -> Path:
        return Path(self.runs_dir) / run_id / "state.json"

    def _write_state(self, run_id: str, payload: dict[str, Any]) -> None:
        """Écriture atomique : un kill -9 ne doit pas laisser un JSON tronqué."""
        path = self._state_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def _load_state(self, resume: Path, planner_label: str) -> dict[str, Any]:
        try:
            state = json.loads(Path(resume).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ResumeError(f"état de reprise introuvable : {resume}") from exc
        except json.JSONDecodeError as exc:
            raise ResumeError(
                f"état de reprise illisible (JSON tronqué ?) : {resume} — {exc.msg} ligne {exc.lineno}"
            ) from exc
        recorded = str(state.get("planner") or "")
        wanted = "replay" if planner_label == "replay" else "live"
        if recorded and not recorded.startswith(wanted) and not wanted.startswith(recorded.split(":")[0]):
            raise ResumeError(
                f"reprise refusée : l'état a été écrit en {recorded}, le run demandé est en {wanted}"
            )
        return state

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
        resumed_from = 0
        restored: dict[str, Any] = {}
        if self.resume:
            restored = self._load_state(self.resume, result.planner)
            result.objective = str(restored.get("objective") or objective)
            artifacts.extend(str(name) for name in (restored.get("artifacts") or []))
            result.artifacts = list(artifacts)
            resumed_from = int(restored.get("step_index") or 0)
            result.events.append({"event": "resumed", "from_step": resumed_from})
            if hasattr(self.planner, "skip"):
                self.planner.skip(resumed_from)
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
        history: list[dict[str, Any]] = [dict(item) for item in (restored.get("history") or [])]
        repeats: dict[str, int] = {str(k): int(v) for k, v in (restored.get("repeats") or {}).items()}

        def snapshot(status_value: str = "running", step_index: int = 0) -> None:
            """État reprenable : objectif, historique, artefacts, numérotation."""
            if not self.save_state:
                return
            self._write_state(
                run_id,
                {
                    "run_id": run_id,
                    "objective": result.objective,
                    "scenario": self.scenario,
                    "planner": result.planner,
                    "max_steps": self.max_steps,
                    "step_index": step_index,
                    "status": status_value,
                    "history": history,
                    "repeats": repeats,
                    "artifacts": list(artifacts),
                    "resumed_at": list(restored.get("resumed_at") or [])
                    + ([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())] if restored else []),
                },
            )
        nudges = 0  # relances « tu n'as pas écrit le livrable », avant de bloquer
        reviews = 0  # relectures contradictoires, deux au maximum  # anti-boucle : mêmes arguments, même erreur

        for index in range(resumed_from + 1, self.max_steps + 1):
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
                if self.reviewer is not None and reviews >= 2:
                    result.status = "blocked"
                    result.summary = (
                        "bloqué : le relecteur a refusé le livrable deux fois, "
                        "arrêt au lieu de consommer le budget restant."
                    )
                    step = Step(index, thought or "Relecture refusée.", None, {}, result.summary, _ms(started), True)
                    result.steps.append(step)
                    _notify(self.on_step, step)
                    break
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
                reviewed_now = False
                if self.reviewer is not None and reviews < 2:
                    reviews += 1
                    reviewed_now = True
                    contents = {}
                    for name in result.artifacts or produced:
                        candidate = self.workspace / name
                        if candidate.is_file():
                            contents[name] = candidate.read_text(encoding="utf-8", errors="replace")[:4000]
                    try:
                        verdict = self.reviewer.review(result.objective, contents, history)
                    except Exception as exc:  # noqa: BLE001 - un relecteur absent ne doit pas tuer le run
                        verdict = {
                            "verdict": "rejette",
                            "motifs": [f"revue impossible : {exc}"],
                            "corrections": [],
                        }
                    decision = str(verdict.get("verdict") or "rejette")
                    result.events.append(
                        {
                            "event": "review",
                            "verdict": decision,
                            "model": getattr(self.reviewer, "label", "review"),
                            "motifs": list(verdict.get("motifs") or []),
                        }
                    )
                    detail = " ; ".join(verdict.get("motifs") or []) or "sans motif"
                    if verdict.get("corrections"):
                        detail += " | à corriger : " + " ; ".join(verdict["corrections"])
                    step = Step(index, thought or "Relecture du livrable.", "review", {}, f"{decision} : {detail}", _ms(started))
                    result.steps.append(step)
                    _notify(self.on_step, step)
                    if decision != "accepte":
                        history.append(
                            {
                                "thought": "Relecture refusée.",
                                "tool": None,
                                "args": {},
                                "observation": (
                                    f"Le relecteur rejette le livrable. Motifs : {detail}. "
                                    f"Corrige puis réponds final."
                                ),
                            }
                        )
                        snapshot("running", index)
                        continue
                step = Step(
                    index + (1 if reviewed_now else 0),
                    thought or "Objectif atteint.",
                    None,
                    {},
                    "run terminé",
                    _ms(started),
                )
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
            snapshot("running", index)
        else:
            result.status = "budget"
            result.summary = f"Budget de {self.max_steps} étapes atteint sans conclusion."

        for event in result.events:
            event.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        result.artifacts = artifacts
        result.finished_at = time.time()
        self._write_log(result)
        snapshot(result.status, len(result.steps) + resumed_from)
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
