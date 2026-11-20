"""Smoke tests: the three scenarios run end to end, in a temporary workspace.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentdemo.agent import Agent
from agentdemo.planners import ReplayPlanner
from agentdemo.scenarios_loader import get_scenario, list_scenarios
from agentdemo.tools import Sandbox, ToolError, build_registry


class ScenarioTests(unittest.TestCase):
    def run_scenario(self, slug: str):
        scenario = get_scenario(slug)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "ws"
        workspace.mkdir()
        scenario.stage(workspace)
        agent = Agent(
            planner=ReplayPlanner(scenario.cassette()),
            workspace=workspace,
            runs_dir=root / "runs",
            max_steps=scenario.max_steps,
        )
        result = agent.run(scenario.objective, run_id="test")
        return result, workspace

    def test_scenarios_are_discoverable(self) -> None:
        slugs = {s.slug for s in list_scenarios()}
        self.assertEqual({"cyber-brief", "inbox-triage", "dataset-report"}, slugs)

    def test_cyber_brief(self) -> None:
        result, workspace = self.run_scenario("cyber-brief")
        self.assertEqual(result.status, "done")
        self.assertFalse([s for s in result.steps if s.error], "aucune étape ne doit échouer")
        briefing = (workspace / "briefing.md").read_text(encoding="utf-8")
        self.assertIn("Briefing cyber", briefing)
        self.assertIn("20/11/2026", briefing)
        self.assertEqual(briefing.count("Enjeu analyste"), 5)
        self.assertIn("briefing.md", result.artifacts)

    def test_inbox_triage(self) -> None:
        result, workspace = self.run_scenario("inbox-triage")
        self.assertEqual(result.status, "done")
        self.assertFalse([s for s in result.steps if s.error], "aucune étape ne doit échouer")
        self.assertEqual(list((workspace / "inbox").iterdir()), [], "la boîte doit être vide après tri")
        self.assertTrue((workspace / "triaged" / "urgent" / "2026-11-19-incident-client.eml").exists())
        report = (workspace / "rapport-tri.md").read_text(encoding="utf-8")
        self.assertIn("À faire aujourd'hui", report)

    def test_dataset_report(self) -> None:
        result, workspace = self.run_scenario("dataset-report")
        self.assertEqual(result.status, "done")
        self.assertFalse([s for s in result.steps if s.error], "aucune étape ne doit échouer")
        chart = (workspace / "graphique.svg").read_text(encoding="utf-8")
        self.assertIn("<svg", chart)
        self.assertEqual(chart.count("<rect"), 7)  # fond + 6 régions
        synthese = (workspace / "synthese.md").read_text(encoding="utf-8")
        self.assertIn("860 900", synthese)

    def test_budget_is_enforced(self) -> None:
        scenario = get_scenario("cyber-brief")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "ws"
        workspace.mkdir()
        scenario.stage(workspace)
        agent = Agent(
            planner=ReplayPlanner(scenario.cassette()),
            workspace=workspace,
            runs_dir=root / "runs",
            max_steps=2,
        )
        result = agent.run(scenario.objective, run_id="budget")
        self.assertEqual(result.status, "budget")
        self.assertEqual(len(result.steps), 2)


class SandboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sandbox = Sandbox(Path(self.tmp.name) / "ws")
        self.artifacts: list[str] = []
        self.tools = build_registry(self.sandbox, self.artifacts)

    def test_write_then_read(self) -> None:
        self.tools["fs_write"].fn(path="out/test.txt", content="bonjour")
        observation = self.tools["fs_read"].fn(path="out/test.txt")
        self.assertIn("bonjour", observation)
        self.assertEqual(self.artifacts, ["out/test.txt"])

    def test_escape_is_refused(self) -> None:
        for tool, args in [
            ("fs_read", {"path": "../../etc/passwd"}),
            ("fs_write", {"path": "/etc/passwd", "content": "x"}),
        ]:
            with self.assertRaises(ToolError):
                self.tools[tool].fn(**args)

    def test_unknown_tool_is_reported_not_crashed(self) -> None:
        agent = Agent(
            planner=ReplayPlanner([{"thought": "test", "tool": "rm_rf", "args": {}}]),
            workspace=Path(self.tmp.name) / "ws",
            runs_dir=Path(self.tmp.name) / "runs",
            max_steps=1,
        )
        result = agent.run("objectif")
        self.assertEqual(result.status, "budget")
        self.assertTrue(result.steps[0].error)
        self.assertIn("outil inconnu", result.steps[0].observation)


if __name__ == "__main__":
    unittest.main()
