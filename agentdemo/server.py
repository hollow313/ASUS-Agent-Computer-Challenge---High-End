"""Web interface: one page, one button, live view of the agent loop.

Standard library only (``http.server``). Runs are executed in a background
thread; the page polls ``/api/runs/<id>`` and renders steps as they land.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .agent import Agent, Step
from .planners import OpenAICompatPlanner, ReplayPlanner
from .scenarios_loader import get_scenario, list_scenarios
from .tools import build_registry

WEB_DIR = Path(__file__).resolve().parent / "web"


class RunStore:
    """In-memory run registry, with one worker thread per run."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.runs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def start(self, slug: str, mode: str, objective: str | None) -> str:
        scenario = get_scenario(slug)
        run_id = uuid.uuid4().hex[:10]
        workspace = self.data_dir / "runs" / run_id / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        scenario.stage(workspace)

        if mode == "live":
            planner = OpenAICompatPlanner(tools=build_registry(_NullSandbox(), []))
        else:
            planner = ReplayPlanner(scenario.cassette())

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
            "started_at": time.time(),
            "workspace": str(workspace),
        }
        with self.lock:
            self.runs[run_id] = state

        agent = Agent(
            planner=planner,
            workspace=workspace,
            runs_dir=self.data_dir / "runs",
            max_steps=scenario.max_steps,
        )

        def on_step(step: Step) -> None:
            with self.lock:
                state["steps"].append(step.as_dict())

        agent.on_step = on_step

        def worker() -> None:
            try:
                result = agent.run(state["objective"], run_id=run_id)
                payload = result.as_dict()
                with self.lock:
                    state["status"] = payload["status"]
                    state["summary"] = payload["summary"]
                    state["artifacts"] = payload["artifacts"]
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
            if path == "/api/scenarios":
                return self._send_json({"scenarios": [s.as_summary() for s in list_scenarios()]})
            if path == "/healthz":
                return self._send_json({"ok": True})
            if path.startswith("/api/runs/"):
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

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path != "/api/run":
                return self._send_json({"error": "route inconnue"}, status=404)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send_json({"error": "json invalide"}, status=400)
            try:
                run_id = store.start(
                    slug=str(payload.get("scenario", "cyber-brief")),
                    mode=str(payload.get("mode", "replay")),
                    objective=payload.get("objective") or None,
                )
            except KeyError as exc:
                return self._send_json({"error": str(exc)}, status=400)
            return self._send_json({"run_id": run_id}, status=202)

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
            self.send_response(200)
            self.send_header("Content-Type", guessed or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(host: str = "0.0.0.0", port: int = 8080, data_dir: Path | None = None) -> None:
    store = RunStore(data_dir or Path("data"))
    httpd = ThreadingHTTPServer((host, port), make_handler(store))
    print(f"Agent Computer — demo sur http://localhost:{port}  (données dans {store.data_dir})")
    httpd.serve_forever()
