"""Web interface: one page, one button, live view of the agent loop.

Standard library only (``http.server``). Runs are executed in a background
thread; the page polls ``/api/runs/<id>`` and renders steps as they land.
"""

from __future__ import annotations

import json
import shutil
import mimetypes
import threading
import time
import traceback
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .agent import Agent, Step
from .planners import OpenAICompatPlanner, ReplayPlanner, normalize_base_url
from .routing import RoutingError, RoutingTable, Target
from .sandbox import isolation_level, runner_for as _runner_for
from .settings_store import Settings
from .scenarios_loader import get_scenario, list_scenarios
from .skills import SkillStore
from .tools import build_registry

WEB_DIR = Path(__file__).resolve().parent / "web"


class RunStore:
    """In-memory run registry, with one worker thread per run."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.runs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def _stage_inputs(self, workspace: Path) -> list[str]:
        """Copie les données d'entrée configurées dans le run : dossier CSV et rien d'autre."""
        settings = Settings.load(self.data_dir / "settings.json")
        source = Path(settings.inputs.csv_dir) if settings.inputs.csv_dir else None
        if source is None or not source.is_dir():
            return []
        target = workspace / "inputs"
        target.mkdir(parents=True, exist_ok=True)
        copied = []
        for item in sorted(source.glob("*.csv"))[:50]:
            shutil.copy2(item, target / item.name)
            copied.append(f"inputs/{item.name}")
        return copied

    def start(self, slug: str, mode: str, objective: str | None, llm: dict[str, Any] | None = None) -> str:
        scenario = get_scenario(slug)
        if mode == "replay" and not scenario.has_cassette():
            raise ValueError(
                "ce scénario n'a pas encore de cassette : lance-le une fois en mode réel, "
                "puis enregistre la trace depuis l'interface (ou la CLI)"
            )
        run_id = uuid.uuid4().hex[:10]
        workspace = self.data_dir / "runs" / run_id / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        scenario.stage(workspace)
        staged = self._stage_inputs(workspace)
        staged += scenario.stage_inputs(workspace)
        # Store global : une procédure apprise au run N est disponible au run N+1.
        skills = SkillStore(self.data_dir / "skills")
        settings = Settings.load(self.data_dir / "settings.json")
        labels = scenario.pass_labels()
        llm = llm or {}
        routing_decision = None
        routing_chain: list[str] = []
        if mode == "live" and not (llm.get("base_url") and llm.get("model")):
            # aucune cible fournie à la main : c'est la politique de routage qui décide
            try:
                table = RoutingTable.load(self.data_dir / "routing.json")
                decision = table.resolve(objective or scenario.objective, slug)
                routing_decision = table.record(decision, objective or scenario.objective, slug)
                table.save(self.data_dir / "routing.json")
            except RoutingError as exc:
                raise ValueError(f"routage impossible : {exc}") from exc
            routing_chain = table.chain_for(decision.target.id)
            llm = {
                "base_url": decision.target.base_url,
                "model": decision.target.model,
                "api_key": decision.target.api_key,
            }
        if mode == "live":
            base_url = str(llm.get("base_url") or "").strip()
            model = str(llm.get("model") or "").strip()
            if base_url and not base_url.startswith(("http://", "https://")):
                raise ValueError("l'endpoint doit commencer par http:// ou https://")
            if not base_url or not model:
                raise ValueError("mode live : renseigne l'endpoint et le modèle")

        state: dict[str, Any] = {
            "run_id": run_id,
            "scenario": slug,
            "title": scenario.title,
            "objective": objective or scenario.objective,
            "mode": mode,
            "status": "running",
            "steps": [],
            "artifacts": [],
            "summary": "",
            "recap": [],
            "started_at": time.time(),
            "workspace": str(workspace),
            "routing": routing_decision,
            "inputs_staged": staged,
            "network": scenario.network,
            "events": [],
            "isolation": isolation_level(),
        }
        with self.lock:
            self.runs[run_id] = state

        fallback_events: list[dict[str, Any]] = []

        def worker() -> None:
            try:
                for index, label in enumerate(labels):
                    for change in scenario.apply_mutations(index, workspace):
                        applied = {"pass": index + 1, "label": label, "change": change}
                        with self.lock:
                            state.setdefault("mutations", []).append(applied)
                    if mode == "live":
                        planner = _live_planner(llm, routing_chain, self.data_dir, fallback_events)
                    else:
                        planner = ReplayPlanner(scenario.cassette(index))

                    def on_step(step: Step, index: int = index) -> None:
                        payload = step.as_dict()
                        payload["pass"] = index + 1
                        payload["pass_label"] = labels[index]
                        with self.lock:
                            state["steps"].append(payload)

                    agent = Agent(
                        planner=planner,
                        workspace=workspace,
                        runs_dir=self.data_dir / "runs",
                        max_steps=scenario.max_steps,
                        on_step=on_step,
                        skills=skills,
                        settings=settings,
                        children_dir=scenario.root / "children",
                        network_config=scenario.network,
                        runner=_runner_for(workspace, scenario),
                        scenario=slug,
                    )
                    result = agent.run(state["objective"], run_id=f"{run_id}-p{index + 1}")
                    if fallback_events:
                        result.events = list(fallback_events) + list(result.events)
                    with self.lock:
                        state["status"] = result.status
                        state["summary"] = result.summary
                        state["artifacts"] = result.artifacts
                        state["events"] = result.events
                        state["network_effective"] = result.network
                        state["recap"].append(
                            {
                                "label": label or f"passe {index + 1}",
                                "status": result.status,
                                "steps": len(result.steps),
                                "errors": sum(1 for s in result.steps if s.error),
                                "summary": result.summary,
                            }
                        )
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                traceback.print_exc()
                with self.lock:
                    state["status"] = "failed"
                    state["summary"] = f"erreur interne : {exc}"

        threading.Thread(target=worker, daemon=True).start()
        return run_id

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.lock:
            state = self.runs.get(run_id)
            return json.loads(json.dumps(state)) if state else None

    def artifact_path(self, run_id: str, relative: str) -> Path | None:
        with self.lock:
            state = self.runs.get(run_id)
        if not state:
            return None
        root = Path(state["workspace"]).resolve()
        target = (root / relative).resolve()
        if root not in target.parents and target != root:
            return None
        return target if target.is_file() else None


def _live_planner(
    llm: dict[str, Any],
    chain_ids: list[str],
    data_dir: Path,
    sink: list[dict[str, Any]],
) -> Any:
    """Planner live, avec la chaîne de repli déclarée dans la politique de routage."""
    from .planners import FallbackPlanner

    if not chain_ids:
        return OpenAICompatPlanner(
            base_url=str(llm.get("base_url") or ""),
            model=str(llm.get("model") or ""),
            api_key=str(llm.get("api_key") or ""),
            tools=build_registry(_NullSandbox(), []),
        )
    table = RoutingTable.load(Path(data_dir) / "routing.json")
    by_id = {target.id: target for target in table.targets}
    built: list[tuple[str, Any]] = []
    for target_id in chain_ids:
        target = by_id.get(target_id)
        if target is None:
            continue
        built.append(
            (
                target.label or target.id,
                OpenAICompatPlanner(
                    base_url=target.base_url,
                    model=target.model,
                    api_key=target.api_key,
                    tools=build_registry(_NullSandbox(), []),
                ),
            )
        )
    return FallbackPlanner(built, sink.append) if built else FallbackPlanner([])


class _NullSandbox:
    def __init__(self) -> None:
        self.root = Path(".")

    def resolve(self, relative: str) -> Path:
        return Path(relative)


def make_handler(store: RunStore):
    class Handler(BaseHTTPRequestHandler):
        server_version = "agentdemo/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:  # quieter logs
            if "/api/runs/" in (args[0] if args else ""):
                return
            super().log_message(fmt, *args)

        # ---------- routing ----------
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._send_file(WEB_DIR / "index.html")
            if path == "/routing":
                return self._send_file(WEB_DIR / "routing.html")
            if path == "/settings":
                return self._send_file(WEB_DIR / "settings.html")
            if path == "/healthz":
                return self._send_json({"ok": True})
            if path == "/api/scenarios":
                hidden = set(Settings.load(store.data_dir / "settings.json").hidden_scenarios)
                scenarios = [
                    {**sc.as_summary(), "hidden": sc.slug in hidden}
                    for sc in list_scenarios()
                    if sc.slug not in hidden
                ]
                return self._send_json({"scenarios": scenarios})
            if path == "/api/tools":
                from .toolcatalog import CATALOG_DIR, installed

                present = {str(item.get("name")) for item in installed(store.data_dir)}
                items = []
                for folder in sorted(CATALOG_DIR.glob("*/manifest.json")):
                    try:
                        data = json.loads(folder.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        continue
                    name = str(data.get("name") or folder.parent.name)
                    items.append({
                        "name": name,
                        "description": str(data.get("description") or ""),
                        "version": str(data.get("version") or ""),
                        "installed": name in present,
                    })
                return self._send_json({"catalog": items, "installed": sorted(present)})
            if path == "/api/doctor":
                from .doctor import run_checks

                checks = run_checks(store.data_dir)
                return self._send_json({
                    "checks": [
                        {"name": c.name, "status": c.status, "detail": c.detail, "required": c.required}
                        for c in checks
                    ],
                    "blocking": [c.name for c in checks if c.required and c.status == "fail"],
                })
            if path == "/api/inputs/check":
                query = parse_qs(urlparse(self.path).query)
                raw = (query.get("path") or [""])[0].strip()
                if not raw:
                    return self._send_json({"error": "chemin vide"}, status=400)
                target = Path(raw)
                if not target.is_dir():
                    return self._send_json({"exists": False, "error": "dossier introuvable côté serveur"})
                files = sorted(str(p.relative_to(target)) for p in target.rglob("*") if p.is_file())[:20]
                return self._send_json({"exists": True, "count": len(files), "files": files})
            if path == "/api/mcp/catalog":
                catalog = json.loads(
                    (Path(__file__).resolve().parent / "mcp_catalog.json").read_text(encoding="utf-8")
                )
                configured = Settings.load(store.data_dir / "settings.json")
                installed = {server.name for server in configured.mcp_servers}
                for server in catalog["servers"]:
                    server["installed"] = server["name"] in installed
                return self._send_json(catalog)
            if path.startswith("/api/scenarios/") and path.count("/") == 3:
                slug = path.split("/")[3]
                try:
                    from .scenarios_loader import scenario_detail

                    return self._send_json(scenario_detail(slug))
                except KeyError:
                    return self._send_json({"error": f"scénario inconnu : {slug}"}, status=404)
            if path == "/api/settings":
                settings = Settings.load(store.data_dir / "settings.json")
                return self._send_json(
                    {
                        "settings": settings.as_public(),
                        "scenarios": [sc.as_summary() for sc in list_scenarios()],
                    }
                )
            if path == "/api/routing":
                table = RoutingTable.load(store.data_dir / "routing.json")
                return self._send_json(self._routing_public(table))
            if path == "/api/maintenance":
                log = store.data_dir / "maintenance.jsonl"
                lines = log.read_text(encoding="utf-8").splitlines()[-20:] if log.exists() else []
                return self._send_json({"passes": [json.loads(line) for line in lines if line.strip()]})
            if path == "/api/skills":
                store_skills = SkillStore(store.data_dir / "skills")
                return self._send_json({"skills": store_skills.ledger()})
            if path == "/api/llm/models":
                return self._probe_models(parse_qs(urlparse(self.path).query))
            if path.startswith("/api/runs/") and path.endswith("/export"):
                run_id = path.split("/")[3]
                from .export import export_run

                try:
                    exported = export_run(store.data_dir / "runs", run_id)
                except FileNotFoundError:
                    return self._send_json({"error": "run inconnu"}, status=404)
                body = exported.path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition", f'attachment; filename="run-{run_id}.zip"')
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/api/runs/") and path.count("/") == 3:
                run_id = path.split("/")[3]
                state = store.get(run_id)
                if state is None:
                    return self._send_json({"error": "run inconnu"}, status=404)
                return self._send_json(state)
            if path.startswith("/api/artifacts/"):
                _, _, _, run_id, *rest = path.split("/")
                target = store.artifact_path(run_id, unquote("/".join(rest)))
                if target is None:
                    return self._send_json({"error": "fichier inconnu"}, status=404)
                return self._send_file(target, download="dl" in self.path)
            return self._send_json({"error": "route inconnue"}, status=404)

        def do_DELETE(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path.startswith("/api/scenarios/") and path.count("/") == 3:
                slug = path.split("/")[3]
                try:
                    from .scenarios_loader import remove_scenario

                    summary = remove_scenario(slug, store.data_dir)
                except KeyError:
                    return self._send_json({"error": f"scénario inconnu : {slug}"}, status=404)
                except ValueError as exc:
                    return self._send_json({"error": str(exc)}, status=400)
                return self._send_json({"ok": True, "removed": summary})
            return self._send_json({"error": "route inconnue"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send_json({"error": "json invalide"}, status=400)
            if not isinstance(payload, dict):
                return self._send_json({"error": "objet JSON attendu"}, status=400)

            if path == "/api/routing":
                try:
                    table = RoutingTable.load(store.data_dir / "routing.json")
                    if "targets" in payload:
                        table.targets = [Target.from_public(item) for item in payload["targets"] if isinstance(item, dict)]
                    if "rules" in payload:
                        from .routing import Rule

                        table.rules = [
                            Rule(
                                match=str(item.get("match", "")),
                                value=str(item.get("value", "")),
                                target=str(item.get("target", "")),
                                note=str(item.get("note", "")),
                            )
                            for item in payload["rules"]
                        ]
                    if "default_target" in payload:
                        table.default_target = str(payload["default_target"])
                    if "override" in payload:
                        table.override = str(payload["override"] or "")
                    if "sensitive_words" in payload:
                        table.sensitive_words = [str(w) for w in payload["sensitive_words"]]
                    table.save(store.data_dir / "routing.json")
                except (RoutingError, TypeError, KeyError) as exc:
                    return self._send_json({"error": str(exc)}, status=400)
                return self._send_json({"ok": True})
            if path == "/api/routing/decide":
                try:
                    table = RoutingTable.load(store.data_dir / "routing.json")
                    decision = table.resolve(str(payload.get("objective", "")), str(payload.get("scenario", "")))
                except RoutingError as exc:
                    return self._send_json({"error": str(exc)}, status=400)
                out = decision.as_dict()
                if table.override:
                    without_override = RoutingTable(
                        targets=table.targets,
                        rules=table.rules,
                        default_target=table.default_target,
                        sensitive_words=table.sensitive_words,
                    )
                    out["policy_decision"] = without_override.resolve(
                        str(payload.get("objective", "")), str(payload.get("scenario", ""))
                    ).as_dict()
                return self._send_json(out)
            if path == "/api/routing/probe":
                table = RoutingTable.load(store.data_dir / "routing.json")
                target = next((t for t in table.targets if t.id == payload.get("target")), None)
                if target is None:
                    return self._send_json({"error": "cible inconnue"}, status=404)
                return self._probe_models({"base_url": [target.base_url], "api_key": [target.api_key]})
            if path and path.startswith("/api/scenarios/") and path.endswith("/hide"):
                slug = path.split("/")[3]
                settings_path = store.data_dir / "settings.json"
                settings = Settings.load(settings_path)
                hidden = set(settings.hidden_scenarios)
                if bool(payload.get("hidden", True)):
                    hidden.add(slug)
                else:
                    hidden.discard(slug)
                settings.update({"hidden_scenarios": sorted(hidden)})
                settings.save(settings_path)
                return self._send_json({"ok": True, "hidden": sorted(hidden)})
            if path and path.startswith("/api/scenarios/") and path.endswith("/reset"):
                slug = path.split("/")[3]
                try:
                    from .scenarios_loader import reset_scenario

                    restored = reset_scenario(slug)
                except KeyError:
                    return self._send_json({"error": f"scénario inconnu : {slug}"}, status=404)
                except ValueError as exc:
                    return self._send_json({"error": str(exc)}, status=400)
                return self._send_json({"ok": True, "scenario": restored.as_summary()})
            if path == "/api/mcp/test":
                from .mcp_client import McpClientError, call_tool, probe

                settings = Settings.load(store.data_dir / "settings.json")
                name = str(payload.get("name") or "")
                server = next((item for item in settings.mcp_servers if item.name == name), None)
                if server is None:
                    return self._send_json({"error": f"serveur inconnu : {name}"}, status=404)
                try:
                    if payload.get("tool"):
                        result = call_tool(server.command, server.args, str(payload["tool"]), payload.get("args") or {})
                    else:
                        result = probe(server.command, server.args)
                except McpClientError as exc:
                    return self._send_json({"ok": False, "error": str(exc)})
                return self._send_json(result)
            if path == "/api/tools/install":
                from .toolcatalog import install

                try:
                    result = install(
                        store.data_dir,
                        str(payload.get("name") or ""),
                        approved=bool(payload.get("approved")),
                        catalog_dir=None,
                    )
                except Exception as exc:  # CatalogError et refus d'empreinte
                    return self._send_json({"error": str(exc)}, status=400)
                return self._send_json({"ok": True, "installed": str(result)})
            if path == "/api/tools/remove":
                from .toolcatalog import remove

                try:
                    remove(store.data_dir, str(payload.get("name") or ""), approved=True)
                except Exception as exc:
                    return self._send_json({"error": str(exc)}, status=400)
                return self._send_json({"ok": True})
            if path == "/api/maintenance/run":
                from .maintenance import Maintainer

                runs = sorted(
                    (store.data_dir / "runs").glob("*/workspace"),
                    key=lambda item: item.stat().st_mtime,
                    reverse=True,
                )
                report = Maintainer(
                    SkillStore(store.data_dir / "skills"),
                    runs[0] if runs else store.data_dir / "runs" / "maintenance-sandbox",
                    store.data_dir / "maintenance.jsonl",
                ).run_once()
                return self._send_json(report.as_dict())
            if path == "/api/settings":
                try:
                    settings = Settings.load(store.data_dir / "settings.json")
                    settings.update(payload)
                    settings.save(store.data_dir / "settings.json")
                except (ValueError, TypeError) as exc:
                    return self._send_json({"error": str(exc)}, status=400)
                return self._send_json({"ok": True, "settings": settings.as_public()})
            if path == "/api/settings/test-mail":
                from .mailbox import MailError, test_connection

                settings = Settings.load(store.data_dir / "settings.json")
                if payload.get("host"):
                    settings.mail.host = str(payload.get("host"))
                    settings.mail.port = int(payload.get("port") or 993)
                    settings.mail.user = str(payload.get("user") or "")
                    settings.mail.mailbox = str(payload.get("mailbox") or "INBOX")
                    settings.mail.ssl = bool(payload.get("ssl", True))
                    password = str(payload.get("password") or "")
                    if password and password != "********":
                        settings.mail.password = password
                try:
                    return self._send_json({"ok": True, "message": test_connection(settings.mail)})
                except MailError as exc:
                    return self._send_json({"error": str(exc)}, status=400)
            if path.startswith("/api/jobs/"):
                parts = path.split("/")
                job_id = parts[3] if len(parts) > 3 else ""
                action = parts[4] if len(parts) > 4 else ""
                settings = Settings.load(store.data_dir / "settings.json")
                job = next((item for item in settings.jobs if item.id == job_id), None)
                if job is None:
                    return self._send_json({"error": f"tâche inconnue : {job_id}"}, status=404)
                if action == "toggle":
                    job.enabled = not job.enabled
                elif action == "delete":
                    settings.jobs = [item for item in settings.jobs if item.id != job_id]
                elif action == "run":
                    try:
                        run_id = store.start(job.scenario, job.mode, None)
                    except (KeyError, ValueError) as exc:
                        return self._send_json({"error": str(exc)}, status=400)
                    job.last_run_id = run_id
                    job.last_run = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    job.last_status = "lancé à la main"
                else:
                    return self._send_json({"error": f"action inconnue : {action}"}, status=400)
                settings.save(store.data_dir / "settings.json")
                return self._send_json({"ok": True, "settings": settings.as_public()})
            if path.startswith("/api/scenarios/") and path.endswith("/duplicate"):
                slug = path.split("/")[3]
                try:
                    from .scenarios_loader import duplicate_scenario

                    copy = duplicate_scenario(slug, str(payload.get("slug", "")))
                except (ValueError, KeyError, OSError) as exc:
                    return self._send_json({"error": str(exc)}, status=400)
                return self._send_json({"ok": True, "scenario": copy.as_summary()}, status=201)
            if path.startswith("/api/scenarios/") and path.count("/") == 3:
                slug = path.split("/")[3]
                try:
                    from .scenarios_loader import update_scenario

                    updated = update_scenario(slug, payload)
                except KeyError:
                    return self._send_json({"error": f"scénario inconnu : {slug}"}, status=404)
                except (ValueError, TypeError) as exc:
                    return self._send_json({"error": str(exc)}, status=400)
                return self._send_json({"ok": True, "scenario": updated.as_summary()})
            if path == "/api/scenarios":
                try:
                    from .scenarios_loader import create_scenario

                    created = create_scenario(
                        slug=str(payload.get("slug", "")),
                        title=str(payload.get("title", "")),
                        objective=str(payload.get("objective", "")),
                        blurb=str(payload.get("blurb", "")),
                        tags=list(payload.get("tags") or []),
                        max_steps=int(payload.get("max_steps") or 10),
                        network=payload.get("network") or None,
                        exec_config=payload.get("exec") or None,
                        inputs=payload.get("inputs") or None,
                    )
                except (ValueError, KeyError, OSError) as exc:
                    return self._send_json({"error": str(exc)}, status=400)
                return self._send_json({"ok": True, "scenario": created.as_summary()}, status=201)
            if path.startswith("/api/scenarios/") and path.endswith("/record"):
                slug = path.split("/")[3]
                run_id = str(payload.get("run_id", ""))
                try:
                    from .scenarios_loader import record_cassette

                    scenario = get_scenario(slug)
                except KeyError:
                    return self._send_json({"error": f"scénario inconnu : {slug}"}, status=404)
                journals = sorted((store.data_dir / "runs").glob(f"{run_id}*.json"))
                if not journals:
                    return self._send_json({"error": f"run introuvable : {run_id}"}, status=404)
                journal = json.loads(journals[-1].read_text(encoding="utf-8"))
                if journal.get("status") not in ("done", "budget"):
                    return self._send_json(
                        {"error": f"run {run_id} en statut {journal.get('status')}, rien à enregistrer"},
                        status=400,
                    )
                target = record_cassette(scenario, journal.get("steps", []), journal.get("summary", ""))
                return self._send_json({"ok": True, "cassette": str(target.name), "steps": len(scenario.cassette())})
            if path != "/api/run":
                return self._send_json({"error": "route inconnue"}, status=404)
            try:
                run_id = store.start(
                    slug=str(payload.get("scenario", "cyber-brief")),
                    mode=str(payload.get("mode", "replay")),
                    objective=payload.get("objective") or None,
                    llm=payload.get("llm") or None,
                )
            except (KeyError, ValueError) as exc:
                return self._send_json({"error": str(exc)}, status=400)
            return self._send_json({"run_id": run_id}, status=202)

        def _probe_models(self, query: dict[str, list[str]]) -> None:
            """Interroge `/models` d'un endpoint compatible OpenAI et renvoie ce qu'il expose."""
            import urllib.error
            import urllib.request

            base_url = (query.get("base_url") or [""])[0].strip().rstrip("/")
            api_key = (query.get("api_key") or [""])[0].strip()
            if not base_url:
                return self._send_json({"ok": False, "error": "adresse manquante"}, status=400)
            request = urllib.request.Request(f"{base_url}/models", headers={"Accept": "application/json"})
            if api_key:
                request.add_header("Authorization", f"Bearer {api_key}")
            try:
                with urllib.request.urlopen(request, timeout=8) as response:
                    payload = json.loads(response.read().decode("utf-8") or "{}")
            except urllib.error.HTTPError as exc:
                return self._send_json({"ok": False, "error": f"HTTP {exc.code}"})
            except Exception as exc:
                return self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]})
            models = [str(item.get("id")) for item in (payload.get("data") or []) if item.get("id")]
            return self._send_json({"ok": True, "models": models})

        def _routing_public(self, table: RoutingTable) -> dict[str, Any]:
            return {
                "targets": [t.as_public() for t in table.targets],
                "rules": [
                    {"match": r.match, "value": r.value, "target": r.target, "note": r.note} for r in table.rules
                ],
                "default_target": table.default_target,
                "override": table.override,
                "sensitive_words": table.sensitive_words,
                "history": table.history[-20:],
            }

        # ---------- helpers ----------

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, download: bool = False) -> None:
            if not path.is_file():
                return self._send_json({"error": "introuvable"}, status=404)
            body = path.read_bytes()
            guessed, _ = mimetypes.guess_type(path.name)
            content_type = guessed or "application/octet-stream"
            # Sans charset explicite, le navigateur devine latin-1 et les accents
            # des livrables (briefing, rapports) s'affichent en mojibake.
            if content_type.startswith("text/") or content_type in ("image/svg+xml", "application/json"):
                content_type = f"{content_type}; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.end_headers()
            self.wfile.write(body)

    return Handler


def scheduler_loop(store: "RunStore", interval: float = 20.0) -> None:
    """Boucle de planification : lance les tâches arrivées à échéance, une fois chacune.

    Volontairement simple : pas de file de messages, aucune dépendance. Le fichier de réglages
    est relu à chaque tour, donc une tâche ajoutée depuis l'interface est prise en compte sans
    redémarrer le serveur.
    """
    while True:
        try:
            path = store.data_dir / "settings.json"
            settings = Settings.load(path)
            changed = False
            for job in settings.jobs:
                if not job.is_due():
                    continue
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                try:
                    run_id = store.start(job.scenario, job.mode, None)
                    job.last_status = "ok"
                    job.last_run_id = run_id
                except Exception as exc:  # noqa: BLE001 - une tâche qui casse ne doit pas arrêter la boucle
                    job.last_status = f"échec : {str(exc)[:160]}"
                job.last_run = now
                changed = True
                print(f"[planificateur] {job.scenario} lancé ({job.last_status})", flush=True)
            if changed:
                settings.save(path)
        except Exception as exc:  # noqa: BLE001
            print(f"[planificateur] tour ignoré : {exc}", flush=True)
        time.sleep(interval)


def serve(host: str = "0.0.0.0", port: int = 8080, data_dir: Path | None = None) -> None:
    store = RunStore(data_dir or Path("data"))
    httpd = ThreadingHTTPServer((host, port), make_handler(store))
    threading.Thread(target=scheduler_loop, args=(store,), daemon=True).start()
    print(f"Agent Computer, demo sur http://localhost:{port}  (données dans {store.data_dir})")
    print("planificateur actif : les tâches de /settings tournent toutes seules", flush=True)
    httpd.serve_forever()
