"""Smoke tests: the three scenarios run end to end, in a temporary workspace.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import tempfile
import unittest
import zipfile
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
        self.assertEqual(
            {"cyber-brief", "inbox-triage", "dataset-report", "self-repair", "delegation"}, slugs
        )

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

    def test_procedure_can_be_revised(self) -> None:
        """Une procédure périmée peut être réécrite, mais seulement si son nouveau contrat passe."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "ws"
        workspace.mkdir()
        (workspace / "v2.txt").write_text("ok", encoding="utf-8")
        skills = SkillStore(root / "skills")

        skills.write("source", "# Procédure\n\nLire source.txt.", check="path_exists source.txt")
        self.assertEqual(len(skills.recall("source", workspace)), 0, "contrat cassé, rien n'est servi")

        revised = skills.revise(
            "source", "# Procédure\n\nLire v2.txt, source.txt n'existe plus.", "path_exists v2.txt",
            reason="fichier renommé",
        )
        self.assertIsNotNone(revised)
        self.assertEqual(revised.status, "active")
        self.assertEqual(revised.meta["revisions"], "1")
        self.assertEqual(len(skills.recall("source", workspace)), 1, "la révision vérifiée est servie")

        # révision avec un contrat qui ne passe pas : la procédure ne redevient pas servie
        bad = skills.revise("source", "# Procédure\n\nLire nimporte quoi.", "path_exists absent.txt")
        self.assertEqual(bad.status, "stale")
        self.assertEqual(len(skills.recall("source", workspace)), 0)

    def test_conflicting_procedures_are_arbitrated(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        skills = SkillStore(Path(tmp.name) / "skills")
        skills.write("a", "# Procédure\n\nUtiliser la méthode A.", topic="export-csv")
        skills.write("b", "# Procédure\n\nUtiliser la méthode B.", topic="export-csv")

        for _ in range(3):
            skills.feedback("b", True)
        decisions = skills.resolve_conflicts()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["winner"], "b", "la confiance la plus haute gagne")
        self.assertEqual(skills.get("a").status, "superseded")
        self.assertEqual(skills.get("a").meta["superseded_by"], "b")
        self.assertEqual(skills.get("b").status, "active")

    def test_agent_can_delegate_to_sub_agents(self) -> None:
        """Le parent délègue trois zones, relit les livrables et agrège."""
        scenario = get_scenario("delegation")
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
            children_dir=scenario.root / "children",
        )
        result = agent.run(scenario.objective, run_id="deleg")

        self.assertEqual(result.status, "done")
        self.assertFalse([s for s in result.steps if s.error], "aucune étape en erreur")
        for zone in ("nord", "sud", "ouest"):
            self.assertTrue((workspace / "delegations" / zone / "resume.md").exists(), zone)
        self.assertTrue((workspace / "comparatif.md").exists())
        self.assertEqual(len([a for a in result.artifacts if a.startswith("delegations/")]), 3)

    def test_maintenance_repairs_a_renamed_target(self) -> None:
        """Réparation automatique : la cible a été renommée, le mainteneur retrouve le fichier."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "ws"
        workspace.mkdir()
        (workspace / "flux-avis-2027.xml").write_text("<rss/>", encoding="utf-8")
        skills = SkillStore(root / "skills")
        skills.write(
            "flux",
            "# Procédure\n\nLire feeds/flux-avis-112026.xml avant de conclure.",
            check="path_exists feeds/flux-avis-112026.xml",
        )
        self.assertEqual(len(skills.recall("flux", workspace)), 0, "contrat cassé au départ")

        from agentdemo.maintenance import Maintainer

        report = Maintainer(skills, workspace, root / "maintenance.jsonl").run_once()
        self.assertEqual(len(report.repaired), 1, "la procédure doit être réparée")
        repaired = skills.get("flux")
        self.assertEqual(repaired.status, "active")
        self.assertIn("flux-avis-2027.xml", repaired.check)
        self.assertIn("flux-avis-2027.xml", repaired.body, "le corps doit pointer sur la nouvelle cible")
        self.assertTrue((root / "maintenance.jsonl").exists(), "la passe doit être journalisée")

    def test_maintenance_arbitrates_by_evidence(self) -> None:
        """Deux procédures du même sujet : celle dont le contrat passe gagne, même moins confiante."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "ws"
        workspace.mkdir()
        (workspace / "existe.txt").write_text("ok", encoding="utf-8")
        skills = SkillStore(root / "skills")

        skills.write("verifiee", "# Procédure\n\nMéthode qui se vérifie.", check="path_exists existe.txt", topic="export")
        skills.write("fausse", "# Procédure\n\nMéthode qui ne se vérifie pas.", check="path_exists absent.txt", topic="export")
        for _ in range(3):
            skills.feedback("fausse", True)

        from agentdemo.maintenance import Maintainer

        report = Maintainer(skills, workspace, root / "maintenance.jsonl").run_once()
        self.assertTrue(report.superseded or report.retired, "un conflit doit être tranché")
        self.assertEqual(skills.get("verifiee").status, "active", "la preuve prime sur la confiance")

    def test_vram_planning_is_consistent(self) -> None:
        """Le dimensionnement doit être monotone : plus de VRAM ne fait jamais tenir moins."""
        from agentdemo.fit import MODELS, fits, plan

        rows_3 = {row["model"]: row for row in plan(3, 8192)}
        rows_32 = {row["model"]: row for row in plan(32, 32768)}
        self.assertEqual(rows_3["qwen2.5-coder-32b"]["quant"], "ne rentre pas", "un 32B ne tient pas sur 3 Go")
        self.assertIn(rows_32["qwen2.5-coder-32b"]["quant"], ("Q4", "Q5"), "un 32B tient en Q4/Q5 sur 32 Go")
        self.assertEqual(rows_32["llama-3.3-70b"]["quant"], "ne rentre pas", "un 70B ne tient pas sur 32 Go")

        # réalité assumée : sur 3 Go, un 7B Q4 ne tient pas entièrement, il est déporté en partie
        # sur le CPU, ce qui explique la latence mesurée
        model = next(m for m in MODELS if m.name == "qwen2.5-coder-7b")
        ok_3go, _, _ = fits(3, model, "Q4", 4096)
        ok_8go, _, _ = fits(8, model, "Q4", 4096)
        self.assertFalse(ok_3go, "3 Go ne suffisent pas pour un 7B Q4, même en contexte court")
        self.assertTrue(ok_8go, "8 Go suffisent pour un 7B Q4 en contexte court")

        rows_16 = {row["model"]: row for row in plan(16, 32768)}
        self.assertEqual(rows_16["qwen2.5-coder-32b"]["quant"], "ne rentre pas", "16 Go ne suffit pas pour un 32B")

    def test_doctor_reports_a_ready_installation(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        from agentdemo.doctor import doctor

        text, code = doctor(Path(tmp.name))
        self.assertEqual(code, 0, "une installation neuve doit être prête")
        self.assertIn("Installation prête", text)
        self.assertIn("Scénarios chargeables", text)

    def test_run_can_be_exported_as_an_archive(self) -> None:
        scenario = get_scenario("dataset-report")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "runs" / "run42" / "workspace"
        workspace.mkdir(parents=True)
        scenario.stage(workspace)
        agent = Agent(
            planner=ReplayPlanner(scenario.cassette()),
            workspace=workspace,
            runs_dir=root / "runs",
            max_steps=scenario.max_steps,
        )
        agent.run(scenario.objective, run_id="run42")

        from agentdemo.export import export_run

        exported = export_run(root / "runs", "run42")
        self.assertTrue(exported.path.exists())
        with zipfile.ZipFile(exported.path) as archive:
            names = archive.namelist()
            self.assertTrue(any(name.startswith("journal/run42") for name in names), names)
            self.assertIn("LISEZ-MOI.txt", names)
            self.assertIn("livrables/synthese.md", names)
            self.assertIn("livrables/graphique.svg", names)
            self.assertNotIn("livrables/ventes-2026-T3.csv", names, "les fixtures ne sont pas des livrables")
            readme = archive.read("LISEZ-MOI.txt").decode()
        self.assertIn("run42", readme)
        self.assertIn("statut", readme)

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
