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
from agentdemo.skills import Skill, SkillStore
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
        self.assertEqual({"cyber-brief", "inbox-triage", "dataset-report", "self-repair"}, slugs)

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

    def test_self_repair_learns_between_two_passes(self) -> None:
        """The point of the feature: the second pass is shorter and error-free."""
        scenario = get_scenario("self-repair")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "ws"
        workspace.mkdir()
        scenario.stage(workspace)
        skills = SkillStore(root / "skills")

        passes = []
        for index in range(2):
            agent = Agent(
                planner=ReplayPlanner(scenario.cassette(index)),
                workspace=workspace,
                runs_dir=root / "runs",
                max_steps=scenario.max_steps,
                skills=skills,
            )
            passes.append(agent.run(scenario.objective, run_id=f"p{index}"))

        first, second = passes
        self.assertEqual(first.status, "done")
        self.assertEqual(second.status, "done")
        self.assertEqual(sum(1 for s in first.steps if s.error), 1, "la passe 1 doit se casser une fois")
        self.assertEqual(sum(1 for s in second.steps if s.error), 0, "la passe 2 ne doit plus échouer")
        self.assertLess(len(second.steps), len(first.steps), "la passe 2 doit être plus courte")
        self.assertTrue((skills.root / "feeds-avis.md").exists(), "la procédure doit être persistée")
        self.assertTrue((workspace / "veille.md").exists())

    def test_procedure_lifecycle(self) -> None:
        """Une procédure se vérifie : contrat cassé = retrait, feedback = confiance."""
        scenario = get_scenario("self-repair")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "ws"
        workspace.mkdir()
        scenario.stage(workspace)
        skills = SkillStore(root / "skills")

        passes = []
        for index in range(3):
            scenario.apply_mutations(index, workspace)
            agent = Agent(
                planner=ReplayPlanner(scenario.cassette(index)),
                workspace=workspace,
                runs_dir=root / "runs",
                max_steps=scenario.max_steps,
                skills=skills,
            )
            passes.append(agent.run(scenario.objective, run_id=f"p{index}"))

        self.assertTrue(all(run.status == "done" for run in passes), "les trois passes doivent aboutir")
        self.assertLess(len(passes[1].steps), len(passes[0].steps), "la passe 2 doit être plus courte")
        retired = list((skills.root / "retired").glob("*.md"))
        self.assertEqual(len(retired), 1, "la procédure fausse doit être mise à la retraite")
        active = skills.get("feeds-avis")
        self.assertIsNotNone(active)
        self.assertEqual(active.status, "active")
        self.assertIn("flux-avis-2027", active.check, "le contrat doit pointer sur la nouvelle source")
        # la procédure remplacée repart à zéro, mais l'ancienne garde la trace de son succès
        from agentdemo.skills import parse as parse_skill
        retired_meta, _ = parse_skill(retired[0].read_text(encoding="utf-8"))
        self.assertGreaterEqual(int(retired_meta.get("success", "0")), 1, "le succès doit être compté")
        self.assertEqual(active.uses, 0, "une procédure remplacée repart avec un compteur neuf")

    def test_skill_contract_detects_a_dead_lesson(self) -> None:
        """Le cœur du dispositif : une procédure dont le fichier a disparu n'est plus servie."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "ws"
        workspace.mkdir()
        (workspace / "existe.txt").write_text("ok", encoding="utf-8")
        skills = SkillStore(root / "skills")

        skills.write(
            "verifie",
            "# Procédure\n\nLe fichier existe.txt est la source.",
            check="path_exists existe.txt",
        )
        self.assertEqual(len(skills.recall("", workspace)), 1)

        (workspace / "existe.txt").unlink()
        self.assertEqual(len(skills.recall("", workspace)), 0, "contrat cassé, procédure écartée")
        self.assertEqual(len(list((skills.root / "retired").glob("*.md"))), 1)

        # une procédure sans contrat reste servie, mais n'offre aucune garantie
        skills.write("sans-contrat", "# Procédure\n\nRien à vérifier ici.")
        self.assertEqual(len(skills.recall("sans-contrat", workspace)), 1)

    def test_confidence_and_pruning(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        skills = SkillStore(Path(tmp.name) / "skills")
        skill = skills.write("fragile", "# Procédure\n\nFait quelque chose de douteux.")
        self.assertEqual(round(100 * skill.confidence), 50, "une procédure neuve part à 50 %")

        skills.feedback("fragile", True)
        self.assertEqual(round(100 * skills.get("fragile").confidence), 67)
        skills.feedback("fragile", False)
        self.assertEqual(round(100 * skills.get("fragile").confidence), 50)
        self.assertEqual(skills.get("fragile").uses, 2)

        self.assertEqual(skills.prune(min_confidence=0.6, min_uses=2), ["fragile"])
        self.assertIsNone(skills.get("fragile"))
        self.assertEqual(len(list((skills.root / "retired").glob("*.md"))), 1)

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
