"""Perception : une image entre dans le run, un outil la mesure, le modèle la lit."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from agentdemo import scenarios_loader as loader
from agentdemo.agent import Agent
from agentdemo.planners import OpenAICompatPlanner, ReplayPlanner
from agentdemo.scenarios_loader import get_scenario, vision_data_url, vision_image_path
from agentdemo.tools import Sandbox, ToolError, build_registry


class VisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.previous = os.environ.get("AGENTDEMO_DATA_DIR")
        os.environ["AGENTDEMO_DATA_DIR"] = self.tmp.name
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        if self.previous is None:
            os.environ.pop("AGENTDEMO_DATA_DIR", None)
        else:
            os.environ["AGENTDEMO_DATA_DIR"] = self.previous

    def test_scenario_without_vision_keeps_text_only_message(self) -> None:
        """Sans vision, le message reste une chaîne : rien ne change pour les scénarios existants."""
        planner = OpenAICompatPlanner(base_url="http://127.0.0.1:9/v1", model="test")
        self.assertIsNone(planner.image_data_url)
        self.assertIsNone(vision_data_url(get_scenario("cyber-brief")))

    def test_vision_scenario_sends_two_parts_once(self) -> None:
        """L'image part dans le premier message, sous forme de deux parts, une seule fois."""
        scenario = get_scenario("capture-audit")
        url = vision_data_url(scenario)
        self.assertTrue(url.startswith("data:image/png;base64,"))
        planner = OpenAICompatPlanner(base_url="http://127.0.0.1:9/v1", model="test", image_data_url=url)
        sent = {}

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": '{"final": "ok"}'}}]}).encode()

        import urllib.request
        from unittest import mock

        def fake_urlopen(request, timeout=None):
            sent["payload"] = json.loads(request.data.decode())
            return Reply()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            planner.next_action("analyse la capture", [])

        messages = sent["payload"]["messages"]
        first_user = messages[1]
        self.assertIsInstance(first_user["content"], list)
        kinds = [part["type"] for part in first_user["content"]]
        self.assertEqual(kinds, ["text", "image_url"])

    def test_missing_image_is_refused_with_a_clear_message(self) -> None:
        scenario = loader.create_scenario("vision-absente", "V", "analyse", vision={"image": "absente.png"})
        self.assertFalse((scenario.root / "fixtures" / "absente.png").exists())
        with self.assertRaises(ValueError) as caught:
            vision_image_path(get_scenario("vision-absente"))
        self.assertIn("absente", str(caught.exception))

    def test_image_above_the_limit_is_refused(self) -> None:
        scenario = loader.create_scenario(
            "vision-lourde", "V", "analyse", vision={"image": "grosse.png", "max_bytes": 1000}
        )
        fixtures = scenario.root / "fixtures"
        fixtures.mkdir(parents=True, exist_ok=True)
        head = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"IHDR" + (1440).to_bytes(4, "big") + (900).to_bytes(4, "big")
        (fixtures / "grosse.png").write_bytes(head + b"\x00" * 3000)
        with self.assertRaises(ValueError) as caught:
            vision_image_path(get_scenario("vision-lourde"))
        self.assertIn("trop lourde", str(caught.exception))
        self.assertIn("plafond", str(caught.exception))

    def test_file_that_is_not_an_image_is_refused(self) -> None:
        scenario = loader.create_scenario("vision-faux", "V", "analyse", vision={"image": "faux.png"})
        fixtures = scenario.root / "fixtures"
        fixtures.mkdir(parents=True, exist_ok=True)
        (fixtures / "faux.png").write_bytes(b"ceci n est pas une image")
        with self.assertRaises(ValueError) as caught:
            vision_image_path(get_scenario("vision-faux"))
        self.assertIn("pas une image", str(caught.exception))

    def test_path_traversal_in_vision_image_is_refused(self) -> None:
        loader.create_scenario("vision-traversee", "V", "analyse", vision={"image": "../secret.png"})
        with self.assertRaises(ValueError) as caught:
            vision_image_path(get_scenario("vision-traversee"))
        self.assertIn("simple nom de fichier", str(caught.exception))

    def test_replay_writes_the_report_and_probes_the_image(self) -> None:
        """Le replay du scénario écrit le rapport et journalise la mesure de l'image."""
        scenario = get_scenario("capture-audit")
        root = Path(self.tmp.name)
        workspace = root / "runs" / "cap" / "workspace"
        workspace.mkdir(parents=True)
        scenario.stage(workspace)

        result = Agent(
            planner=ReplayPlanner(scenario.cassette(0)),
            workspace=workspace,
            runs_dir=root / "runs",
            max_steps=scenario.max_steps,
            scenario="capture-audit",
        ).run(scenario.objective, run_id="cap")

        self.assertEqual(result.status, "done")
        self.assertIn("RAPPORT-CAPTURE.md", result.artifacts)
        self.assertNotIn("capture.png", result.artifacts, "une image d'entrée n'est pas un livrable")
        probe = next(step for step in result.steps if step.tool == "image_probe")
        self.assertIn("1440 x 900", probe.observation)
        report = (workspace / "RAPPORT-CAPTURE.md").read_text(encoding="utf-8")
        self.assertGreaterEqual(report.count("|"), 6)
        self.assertIn("pixels", report)

    def test_image_probe_reports_dimensions_and_refuses_oversized(self) -> None:
        tools = build_registry(Sandbox(Path(self.tmp.name)), [])
        workspace = Path(self.tmp.name)
        (workspace / "petite.png").write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0d" + b"IHDR"
            + (640).to_bytes(4, "big") + (480).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
        )
        out = tools["image_probe"].fn("petite.png")
        self.assertIn("640 x 480", out)
        self.assertIn("PNG", out)

        (workspace / "lourde.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1_600_000)
        with self.assertRaises(ToolError) as caught:
            tools["image_probe"].fn("lourde.png")
        self.assertIn("plafond", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
