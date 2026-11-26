"""Le mode live, testé sans modèle réel : un faux endpoint compatible OpenAI.

Ce test existe pour une raison simple : jusqu'ici, prouver que le mode live fonctionne demandait un modèle
installé, donc une machine équipée. Ici, un serveur local joue le rôle du modèle, et le test vérifie que la
boucle écrit vraiment un livrable et sort en `done`.

Le faux serveur répond comme LM Studio ou Ollama : `/v1/models` puis `/v1/chat/completions`, avec deux
réponses scriptées (un appel d'outil puis une conclusion).
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from agentdemo.agent import Agent
from agentdemo.planners import OpenAICompatPlanner
from agentdemo.tools import Sandbox, build_registry

TOOL_CALL = {
    "thought": "J'écris le livrable demandé.",
    "tool": "fs_write",
    "args": {"path": "pico.md", "content": "# pico\n\ntrois lignes de résumé\n"},
}
FINAL = {"thought": "C'est écrit.", "final": "pico.md écrit."}


class FakeModel(BaseHTTPRequestHandler):
    """Deux réponses, dans l'ordre : un outil, puis une conclusion."""

    replies: list[dict] = [TOOL_CALL, FINAL]

    def do_GET(self) -> None:  # noqa: N802 - nom imposé par http.server
        if self.path.rstrip("/").endswith("/models"):
            body = json.dumps({"data": [{"id": "fake-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - nom imposé par http.server
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        reply = self.replies.pop(0) if self.replies else FINAL
        body = json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence : un test ne bavarde pas
        return


class LiveWithoutModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        FakeModel.replies = [TOOL_CALL, FINAL]
        self.server = HTTPServer(("127.0.0.1", 0), FakeModel)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def test_live_mode_writes_a_deliverable_against_a_fake_endpoint(self) -> None:
        workspace = self.root / "runs" / "live-fake" / "workspace"
        workspace.mkdir(parents=True)
        sandbox = Sandbox(workspace)
        tools = build_registry(sandbox, [], self.root / "runs")
        planner = OpenAICompatPlanner(
            base_url=f"http://127.0.0.1:{self.port}/v1",
            model="fake-model",
            tools=tools,
            timeout=10,
        )
        result = Agent(
            planner=planner,
            workspace=workspace,
            runs_dir=self.root / "runs",
            max_steps=4,
            scenario="live-fake",
        ).run("écris pico.md", run_id="live-fake")

        self.assertEqual(result.status, "done", result.summary)
        self.assertIn("pico.md", result.artifacts)
        self.assertTrue((workspace / "pico.md").exists())
        self.assertGreaterEqual(len(result.steps), 2)

    def test_unreachable_endpoint_fails_with_a_clear_message(self) -> None:
        """Un port fermé doit produire une erreur lisible, pas une trace."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            dead_port = probe.getsockname()[1]
        planner = OpenAICompatPlanner(
            base_url=f"http://127.0.0.1:{dead_port}/v1", model="fake", timeout=2
        )
        with self.assertRaises(Exception) as caught:
            planner.next_action("objectif", [])
        self.assertIn("impossible", str(caught.exception).lower())


if __name__ == "__main__":
    unittest.main()
