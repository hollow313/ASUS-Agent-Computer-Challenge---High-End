"""Smoke tests: the three scenarios run end to end, in a temporary workspace.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import json
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
            {"cyber-brief", "inbox-triage", "dataset-report", "self-repair", "delegation", "local-audit"}, slugs
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

    def test_delegation_spawns_a_live_child(self) -> None:
        """En mode réel, un nom de sous-agent inconnu crée un sous-agent vivant au lieu d'échouer."""
        from agentdemo.planners import ReplayPlanner as RP

        class FakeLivePlanner(RP):
            label = "live:fake"

            def __init__(self) -> None:
                super().__init__([])
                self.tools = {}
                self.children = 0

            def child(self):
                self.children += 1
                return RP([{"thought": "écrit la synthèse", "tool": "fs_write",
                            "args": {"path": "resume.md", "content": "# zone nord\nok"}},
                           {"thought": "fini", "final": "zone analysée"}])

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "run" / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "regions").mkdir()

        planner = FakeLivePlanner()
        planner.trace = [{"thought": "délègue la zone nord", "tool": "spawn_agent",
                          "args": {"objective": "analyse la zone nord", "name": "nord", "max_steps": 3}},
                         {"thought": "fini", "final": "délégation terminée"}]
        children = root / "children"
        children.mkdir()
        agent = Agent(
            planner=planner, workspace=workspace, runs_dir=root / "run", max_steps=4, children_dir=children
        )
        result = agent.run("analyse les zones")

        self.assertEqual(planner.children, 1, "le sous-agent aurait dû être créé")
        self.assertIn("(live)", result.steps[0].observation)
        self.assertIn("delegations/nord/resume.md", result.steps[0].observation)
        self.assertTrue((workspace / "delegations" / "nord" / "resume.md").exists())

    def test_repeated_successful_call_stops_the_run(self) -> None:
        """Un modèle qui relit dix fois le même fichier sans avancer ne doit pas brûler le budget."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "run" / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "note.txt").write_text("contenu", encoding="utf-8")
        call = {"thought": "je relis", "tool": "fs_read", "args": {"path": "note.txt"}}
        agent = Agent(planner=ReplayPlanner([dict(call) for _ in range(10)]),
                      workspace=workspace, runs_dir=root / "run", max_steps=10)
        result = agent.run("lis le fichier")
        self.assertEqual(result.status, "blocked")
        self.assertLessEqual(len(result.steps), 6, "l'arrêt doit venir avant le budget")

    def test_string_arguments_are_parsed(self) -> None:
        """Un petit modèle renvoie parfois args en chaîne JSON : on l'accepte au lieu d'échouer."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "run" / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "note.txt").write_text("bonjour", encoding="utf-8")
        tape = [
            {"thought": "je lis", "tool": "fs_read", "args": '{"path": "note.txt"}'},
            {"thought": "fini", "final": "lu"},
        ]
        agent = Agent(planner=ReplayPlanner(tape), workspace=workspace, runs_dir=root / "run", max_steps=4)
        result = agent.run("lis note.txt")
        self.assertEqual(result.status, "done")
        self.assertFalse(result.steps[0].error)
        self.assertIn("bonjour", result.steps[0].observation)

    def test_missing_file_suggests_the_real_path(self) -> None:
        """Une erreur de chemin renvoie le chemin réel du fichier, pas juste « introuvable »."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "run" / "workspace"
        (workspace / "regions").mkdir(parents=True)
        (workspace / "regions" / "nord.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        from agentdemo.tools import Sandbox, ToolError, build_registry

        registry = build_registry(Sandbox(workspace), [])
        with self.assertRaises(ToolError) as ctx:
            registry["csv_profile"].fn("nord.csv")
        self.assertIn("regions/nord.csv", str(ctx.exception))

    def test_repeated_failure_stops_the_run(self) -> None:
        """Trois fois le même appel en échec : le run s'arrête au lieu de brûler le budget."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "run" / "workspace"
        workspace.mkdir(parents=True)
        stuck = {"thought": "je réessaie", "tool": "fs_read", "args": {"path": "inconnu.txt"}}
        agent = Agent(planner=ReplayPlanner([stuck, dict(stuck), dict(stuck)]),
                      workspace=workspace, runs_dir=root / "run", max_steps=10)
        result = agent.run("lis un fichier absent")
        self.assertEqual(result.status, "blocked")
        self.assertIn("3 fois", result.summary)
        self.assertIn("budget", result.summary.lower())

    def test_scenario_created_then_recorded_is_replayable(self) -> None:
        """Un scénario créé depuis l'interface devient rejouable une fois sa trace enregistrée."""
        import os
        from agentdemo import scenarios_loader as loader

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        previous = os.environ.get("AGENTDEMO_DATA_DIR")
        os.environ["AGENTDEMO_DATA_DIR"] = tmp.name
        self.addCleanup(lambda: os.environ.__setitem__("AGENTDEMO_DATA_DIR", previous) if previous else os.environ.pop("AGENTDEMO_DATA_DIR", None))

        scenario = loader.create_scenario(
            slug="audit-liens", title="Audit de liens", objective="écris liens.md", tags=["audit"]
        )
        self.assertFalse(scenario.has_cassette(), "un scénario neuf n'a pas de cassette")
        with self.assertRaises(ValueError):
            loader.create_scenario(slug="audit-liens", title="doublon", objective="x")
        with self.assertRaises(ValueError):
            loader.create_scenario(slug="Bad Slug!", title="t", objective="o")

        steps = [
            {"index": 1, "thought": "je liste", "tool": "fs_list", "args": {"path": "."}, "observation": "index.html"},
            {"index": 2, "thought": "j'écris", "tool": "fs_write", "args": {"path": "liens.md", "content": "# liens"},
             "observation": "écrit"},
            {"index": 3, "thought": "fini", "tool": None, "args": {}, "observation": "run terminé"},
        ]
        cassette = loader.record_cassette(scenario, steps, "audit terminé")
        self.assertTrue(cassette.exists())
        replayable = loader.get_scenario("audit-liens")
        self.assertTrue(replayable.has_cassette())
        self.assertEqual(len(replayable.cassette()), 3)

        workspace = Path(tmp.name) / "run" / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "index.html").write_text("<a href='/x'>x</a>", encoding="utf-8")
        agent = Agent(planner=ReplayPlanner(replayable.cassette()), workspace=workspace,
                      runs_dir=Path(tmp.name) / "run", max_steps=5)
        result = agent.run("écris liens.md")
        self.assertEqual(result.status, "done")
        self.assertTrue((workspace / "liens.md").exists())

    def test_settings_mask_the_mail_password(self) -> None:
        """Le mot de passe IMAP est stocké mais jamais renvoyé en clair."""
        from agentdemo.settings_store import SECRET_MASK, Settings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "settings.json"
        settings = Settings()
        settings.update(
            {
                "mail": {"host": "imap.example.com", "user": "boite@example.com", "password": "secret-123"},
                "inputs": {"csv_dir": tmp.name, "feeds": ["https://exemple.fr/rss"]},
            }
        )
        settings.save(path)
        self.assertEqual(oct(path.stat().st_mode)[-3:], "600", "le fichier contient un secret")

        public = settings.as_public()
        self.assertEqual(public["mail"]["password"], SECRET_MASK)
        self.assertNotIn("secret-123", json.dumps(public))
        self.assertTrue(public["mail"]["configured"])

        # un enregistrement qui renvoie le masque ne doit pas écraser le mot de passe
        again = Settings.load(path)
        again.update({"mail": {"host": "imap.example.com", "user": "boite@example.com", "password": SECRET_MASK}})
        self.assertEqual(again.mail.password, "secret-123")

    def test_job_schedule_computes_the_next_run(self) -> None:
        from datetime import datetime, timedelta, timezone
        from agentdemo.settings_store import Job

        now = datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc)
        daily = Job(id="a", scenario="cyber-brief", schedule="daily_at", value="08:00")
        self.assertEqual(daily.next_run(now), "2026-11-20T08:00:00Z")
        self.assertFalse(daily.is_due(now))
        self.assertTrue(daily.is_due(datetime(2026, 11, 20, 8, 1, tzinfo=timezone.utc)))

        late = Job(id="b", scenario="cyber-brief", schedule="daily_at", value="07:00")
        self.assertEqual(late.next_run(now), "2026-11-20T07:00:00Z", "échéance passée : la tâche est en retard")
        self.assertTrue(late.is_due(now), "une tâche jamais lancée rattrape son échéance")

        done = Job(id="b2", scenario="cyber-brief", schedule="daily_at", value="07:00",
                   last_run="2026-11-20T07:00:04Z")
        self.assertFalse(done.is_due(now), "déjà lancée aujourd'hui")
        self.assertEqual(done.next_run(now), "2026-11-21T07:00:00Z")

        hourly = Job(id="c", scenario="cyber-brief", schedule="every_minutes", value="30")
        hourly.last_run = "2026-11-20T06:50:00Z"
        self.assertEqual(hourly.next_run(now), "2026-11-20T07:20:00Z")
        self.assertFalse(hourly.is_due(now))
        self.assertTrue(hourly.is_due(datetime(2026, 11, 20, 7, 21, tzinfo=timezone.utc)))

        with self.assertRaises(ValueError):
            from agentdemo.settings_store import Settings

            bad = Settings()
            bad.jobs = [Job(id="d", scenario="x", schedule="daily_at", value="25:00")]
            bad.validate()

    def test_inputs_are_staged_into_the_run(self) -> None:
        """Le dossier de CSV configuré est copié dans inputs/ et visible des outils."""
        import os
        from agentdemo.server import RunStore

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        csv_dir = root / "csv"
        csv_dir.mkdir()
        (csv_dir / "ventes.csv").write_text("region,ca\nnord,100\nsud,50\n", encoding="utf-8")
        from agentdemo.settings_store import Settings

        settings = Settings.load(root / "settings.json")
        settings.inputs.csv_dir = str(csv_dir)
        settings.save(root / "settings.json")

        previous = os.environ.get("AGENTDEMO_DATA_DIR")
        os.environ["AGENTDEMO_DATA_DIR"] = str(root)
        self.addCleanup(lambda: os.environ.pop("AGENTDEMO_DATA_DIR", None) if previous is None else os.environ.__setitem__("AGENTDEMO_DATA_DIR", previous))

        store = RunStore(root)
        run_id = store.start("dataset-report", "replay", None)
        for _ in range(100):
            if store.runs[run_id]["status"] != "running":
                break
            import time as _t

            _t.sleep(0.05)
        staged = list((root / "runs" / run_id / "workspace" / "inputs").glob("*.csv"))
        self.assertEqual([p.name for p in staged], ["ventes.csv"])

    def test_mail_tools_require_a_configured_account(self) -> None:
        """Sans compte, l'outil refuse avec un message actionnable ; avec un compte injoignable, il dit pourquoi."""
        from agentdemo.settings_store import MailConfig, Settings
        from agentdemo.tools import Sandbox, ToolError, build_registry

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        sandbox = Sandbox(Path(tmp.name))

        registry = build_registry(sandbox, [])
        with self.assertRaises(ToolError) as ctx:
            registry["mail_list"].fn()
        self.assertIn("/settings", str(ctx.exception))

        settings = Settings()
        settings.mail = MailConfig(host="127.0.0.1", port=1, user="x@example.com", password="p", ssl=False)
        registry = build_registry(sandbox, [], settings=settings)
        with self.assertRaises(ToolError) as ctx:
            registry["mail_list"].fn(limit=1)
        self.assertIn("connexion IMAP impossible", str(ctx.exception))


    def test_command_sandbox_runs_and_reports_isolation(self) -> None:
        """Une commande tourne, et le bac à sable réellement utilisé est annoncé."""
        from agentdemo.sandbox import CommandSandbox, isolation_level

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        workspace = Path(tmp.name)
        (workspace / "note.txt").write_text("bonjour", encoding="utf-8")
        runner = CommandSandbox(workspace, allow_unsandboxed=True)
        result = runner.run("cat note.txt")
        self.assertEqual(result.returncode, 0)
        self.assertIn("bonjour", result.stdout)
        self.assertIn(result.isolation.split(" ")[0], {"bwrap", "unshare", "aucune"})
        self.assertEqual(isolation_level(), isolation_level(), "la détection est stable")

    def test_command_sandbox_timeout(self) -> None:
        from agentdemo.sandbox import CommandSandbox

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        runner = CommandSandbox(Path(tmp.name), timeout=1, allow_unsandboxed=True)
        result = runner.run("sleep 5")
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, 124)

    def test_command_sandbox_refuses_without_isolation(self) -> None:
        """Sans bwrap ni unshare, et sans déclaration du scénario, l'exécution est refusée."""
        from agentdemo.sandbox import CommandSandbox, SandboxError, isolation_level

        if isolation_level() != "aucune":
            self.skipTest("un bac à sable noyau est disponible sur cette machine")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        runner = CommandSandbox(Path(tmp.name))
        with self.assertRaises(SandboxError):
            runner.run("echo interdit")

    def test_network_policy_deny_and_allowlist(self) -> None:
        """deny refuse tout ; allowlist accepte l'hôte déclaré et refuse les autres, en journalisant."""
        import http.server
        import threading

        from agentdemo.tools import NetworkPolicy, ToolError

        handler = http.server.SimpleHTTPRequestHandler
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        events: list[dict] = []
        deny = NetworkPolicy({"mode": "deny"}, events)
        with self.assertRaises(ToolError):
            deny.check(f"http://127.0.0.1:{port}/")
        self.assertEqual(events[0]["event"], "network_denied")

        allow = NetworkPolicy({"mode": "allowlist", "hosts": ["127.0.0.1"]}, events)
        allow.check(f"http://127.0.0.1:{port}/")  # ne lève pas
        with self.assertRaises(ToolError):
            allow.check("http://exemple.invalid/")
        self.assertEqual(allow.as_dict()["network_mode"], "allowlist")

    def test_run_tool_is_journaled_and_network_denied_is_recorded(self) -> None:
        from agentdemo.sandbox import CommandSandbox
        from agentdemo.tools import NetworkPolicy, ToolError, Sandbox, build_registry

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        workspace = Path(tmp.name)
        events: list[dict] = []
        registry = build_registry(
            Sandbox(workspace),
            [],
            network=NetworkPolicy({"mode": "deny"}, events),
            runner=CommandSandbox(workspace, allow_unsandboxed=True),
            events=events,
        )
        observation = registry["run"].fn("echo audit")
        self.assertIn("audit", observation)
        self.assertEqual(events[-1]["event"], "exec")
        with self.assertRaises(ToolError):
            registry["http_get"].fn("http://exemple.invalid/")
        self.assertEqual(events[-1]["event"], "network_denied")

    def test_local_audit_scenario_learns_between_passes(self) -> None:
        """Le scénario d'audit produit son rapport, et la seconde passe coûte moins d'étapes."""
        import os

        scenario = get_scenario("local-audit")
        self.assertEqual(scenario.network["mode"], "deny")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        previous = os.environ.get("AGENTDEMO_DATA_DIR")
        os.environ["AGENTDEMO_DATA_DIR"] = str(root)
        self.addCleanup(
            lambda: os.environ.pop("AGENTDEMO_DATA_DIR", None)
            if previous is None
            else os.environ.__setitem__("AGENTDEMO_DATA_DIR", previous)
        )
        from agentdemo.sandbox import CommandSandbox
        from agentdemo.skills import SkillStore

        workspace = root / "runs" / "audit" / "workspace"
        workspace.mkdir(parents=True)
        scenario.stage(workspace)
        skills = SkillStore(root / "skills")
        lengths = []
        for index in range(2):
            agent = Agent(
                planner=ReplayPlanner(scenario.cassette(index)),
                workspace=workspace,
                runs_dir=root / "runs",
                max_steps=scenario.max_steps,
                skills=skills,
                network_config=scenario.network,
                runner=CommandSandbox(workspace, allow_unsandboxed=True),
                scenario="local-audit",
            )
            result = agent.run(scenario.objective, run_id=f"audit-p{index + 1}")
            lengths.append(len(result.steps))
            self.assertEqual(result.status, "done")
        self.assertLess(lengths[1], lengths[0], "la mémoire procédurale doit raccourcir la passe 2")
        report = (workspace / "RAPPORT-AUDIT.md").read_text(encoding="utf-8")
        self.assertIn("203.0.113.42", report)
        self.assertIn("3306", report)
        self.assertTrue(any("bruteforce" in skill.name for skill in skills.list()))

    def test_interactive_refusal_is_journaled(self) -> None:
        """Un refus de l'opérateur devient une observation, pas un crash, et il est tracé."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "run" / "workspace"
        workspace.mkdir(parents=True)
        tape = [
            {"thought": "j'écris le livrable", "tool": "fs_write",
             "args": {"path": "sortie.md", "content": "contenu"}},
            {"thought": "je conclus", "final": "terminé"},
        ]
        agent = Agent(
            planner=ReplayPlanner(tape),
            workspace=workspace,
            runs_dir=root / "run",
            max_steps=4,
            approver=lambda tool, args: False,
        )
        result = agent.run("écris un fichier")
        self.assertFalse((workspace / "sortie.md").exists(), "un refus ne doit rien écrire")
        self.assertTrue(result.steps[0].error)
        self.assertIn("refusé par l'opérateur", result.steps[0].observation)
        approvals = [e for e in result.events if e["event"] == "approval"]
        self.assertEqual(approvals[0]["decision"], "refused")

    def test_scenario_removal_guards(self) -> None:
        import os

        from agentdemo import scenarios_loader as loader

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        previous = os.environ.get("AGENTDEMO_DATA_DIR")
        os.environ["AGENTDEMO_DATA_DIR"] = tmp.name
        self.addCleanup(
            lambda: os.environ.pop("AGENTDEMO_DATA_DIR", None)
            if previous is None
            else os.environ.__setitem__("AGENTDEMO_DATA_DIR", previous)
        )
        created = loader.create_scenario(slug="a-supprimer", title="À supprimer", objective="écris x.md")
        with self.assertRaises(ValueError):
            loader.remove_scenario("self-repair", Path(tmp.name))  # scénario livré
        summary = loader.remove_scenario("a-supprimer", Path(tmp.name), dry_run=True)
        self.assertEqual(summary["scenario"], "a-supprimer")
        self.assertFalse(created.root.exists() is False, "une simulation ne supprime rien")
        loader.remove_scenario("a-supprimer", Path(tmp.name), dry_run=False)
        self.assertFalse(created.root.exists())
        self.assertNotIn("a-supprimer", [sc.slug for sc in loader.list_scenarios()])

    def test_scenario_editing_and_duplication(self) -> None:
        """Un scénario utilisateur s'édite, un scénario livré se duplique au lieu de s'éditer."""
        import os

        from agentdemo import scenarios_loader as loader

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        previous = os.environ.get("AGENTDEMO_DATA_DIR")
        os.environ["AGENTDEMO_DATA_DIR"] = tmp.name
        self.addCleanup(
            lambda: os.environ.pop("AGENTDEMO_DATA_DIR", None)
            if previous is None
            else os.environ.__setitem__("AGENTDEMO_DATA_DIR", previous)
        )
        created = loader.create_scenario(slug="editable", title="Éditable", objective="écris x.md")
        self.assertFalse(created.builtin)

        updated = loader.update_scenario(
            "editable",
            {
                "title": "Éditable v2",
                "max_steps": 7,
                "network": {"mode": "allowlist", "hosts": ["Exemple.Local"]},
                "exec": {"allow_unsandboxed": True, "reason": "test"},
                "inputs": {"dir": str(tmp.name), "feeds": ["https://exemple.local/feed"]},
            },
        )
        self.assertEqual(updated.title, "Éditable v2")
        self.assertEqual(updated.max_steps, 7)
        self.assertEqual(updated.network["hosts"], ["exemple.local"], "les hôtes sont normalisés")
        self.assertTrue(updated.exec_config["allow_unsandboxed"])
        self.assertEqual(updated.inputs["feeds"], ["https://exemple.local/feed"])

        with self.assertRaises(ValueError):
            loader.update_scenario("editable", {"network": {"mode": "allowlist", "hosts": []}})
        # un scénario livré s'édite par surcharge : l'image n'est jamais modifiée
        before = (loader.SCENARIOS_DIR / "cyber-brief" / "scenario.json").read_text(encoding="utf-8")
        patched = loader.update_scenario(
            "cyber-brief", {"title": "Veille maison", "network": {"mode": "allowlist", "hosts": ["exemple.local"]}}
        )
        self.assertEqual(patched.title, "Veille maison")
        self.assertEqual(patched.network["hosts"], ["exemple.local"])
        self.assertTrue(patched.builtin and patched.overridden)
        self.assertEqual(
            (loader.SCENARIOS_DIR / "cyber-brief" / "scenario.json").read_text(encoding="utf-8"), before,
            "le scénario livré ne doit pas être modifié sur disque",
        )
        restored = loader.reset_scenario("cyber-brief")
        self.assertFalse(restored.overridden)
        self.assertNotEqual(restored.title, "Veille maison")

        copy = loader.duplicate_scenario("cyber-brief", "veille-copie")
        self.assertEqual(copy.slug, "veille-copie")
        self.assertFalse(copy.builtin)
        self.assertIn("copie", copy.title)
        detail = loader.scenario_detail("veille-copie")
        self.assertTrue(detail["editable"])
        self.assertTrue(detail["fixtures"])

    def test_scenario_created_with_network_and_inputs(self) -> None:
        """La création depuis l'interface accepte le réseau, l'exécution et un dossier d'entrée."""
        import os

        from agentdemo import scenarios_loader as loader

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        previous = os.environ.get("AGENTDEMO_DATA_DIR")
        os.environ["AGENTDEMO_DATA_DIR"] = tmp.name
        self.addCleanup(
            lambda: os.environ.pop("AGENTDEMO_DATA_DIR", None)
            if previous is None
            else os.environ.__setitem__("AGENTDEMO_DATA_DIR", previous)
        )
        source = Path(tmp.name) / "entrees"
        (source / "sudoers.d").mkdir(parents=True)
        (source / "auth.log").write_text("ligne", encoding="utf-8")
        (source / "sudoers.d" / "webadmin").write_text("regle", encoding="utf-8")

        scenario = loader.create_scenario(
            slug="avec-entrees",
            title="Avec entrées",
            objective="lis les entrées et écris un rapport",
            network={"mode": "allowlist", "hosts": ["Exemple.Local"]},
            exec_config={"allow_unsandboxed": True},
            inputs={"dir": str(source), "feeds": ["https://exemple.local/feed"]},
        )
        self.assertEqual(scenario.network["hosts"], ["exemple.local"])
        self.assertTrue(scenario.exec_config["allow_unsandboxed"])

        workspace = Path(tmp.name) / "run"
        workspace.mkdir()
        copied = scenario.stage_inputs(workspace)
        self.assertIn("inputs/auth.log", copied)
        self.assertIn("inputs/sudoers.d/webadmin", copied)
        self.assertTrue((workspace / "inputs" / "sudoers.d" / "webadmin").exists())

        with self.assertRaises(ValueError):
            loader.create_scenario(
                slug="sans-hote", title="x", objective="y", network={"mode": "allowlist", "hosts": []}
            )

    def test_editing_title_alone_keeps_network(self) -> None:
        """Modifier seulement le titre ne doit pas casser le réseau (bug vu en test)."""
        import os

        from agentdemo import scenarios_loader as loader

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        previous = os.environ.get("AGENTDEMO_DATA_DIR")
        os.environ["AGENTDEMO_DATA_DIR"] = tmp.name
        self.addCleanup(
            lambda: os.environ.pop("AGENTDEMO_DATA_DIR", None)
            if previous is None
            else os.environ.__setitem__("AGENTDEMO_DATA_DIR", previous)
        )
        loader.create_scenario("sans-reseau", "Titre", "objectif", network={"mode": "deny"})
        updated = loader.update_scenario("sans-reseau", {"title": "Titre bis"})
        self.assertEqual(updated.title, "Titre bis")
        self.assertEqual(updated.network.get("mode"), "deny")

    def test_routing_accepts_public_payload(self) -> None:
        """L'interface renvoie les champs calculés (has_key) : l'écriture doit les tolérer."""
        from agentdemo.routing import Target

        target = Target.from_public(
            {
                "id": "local-rapide",
                "label": "7B",
                "base_url": "http://192.168.1.153:1234/v1",
                "model": "qwen2.5-coder-7b-instruct",
                "kind": "local",
                "has_key": False,
                "installed": True,
            }
        )
        self.assertEqual(target.id, "local-rapide")
        self.assertEqual(target.api_key, "")

    def test_mcp_client_handshakes_with_own_server(self) -> None:
        """Le client MCP démarre un vrai serveur, fait la poignée de main et liste ses outils."""
        from agentdemo.mcp_client import probe

        result = probe(sys.executable, ["-m", "agentdemo", "mcp"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["server"]["name"], "vigie")
        names = [tool["name"] for tool in result["tools"]]
        self.assertIn("fs_list", names)
        self.assertIn("skill_recall", names)
        self.assertGreaterEqual(result["count"], 8)

    def test_mcp_client_refuses_missing_command(self) -> None:
        from agentdemo.mcp_client import McpClientError, probe

        with self.assertRaises(McpClientError):
            probe("commande-qui-nexiste-pas-2026")

    def test_hidden_scenarios_are_remembered(self) -> None:
        """Un scénario livré se masque au lieu d'être supprimé, et le réglage se relit."""
        from agentdemo.settings_store import Settings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "settings.json"
        settings = Settings()
        settings.update({"hidden_scenarios": ["self-repair"]})
        settings.save(path)
        self.assertEqual(Settings.load(path).hidden_scenarios, ["self-repair"])
        settings.update({"hidden_scenarios": []})
        settings.save(path)
        self.assertEqual(Settings.load(path).hidden_scenarios, [])

    def test_mcp_servers_are_stored_and_validated(self) -> None:
        from agentdemo.settings_store import Settings

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "settings.json"
        settings = Settings()
        settings.update(
            {
                "mcp_servers": [
                    {"name": "vigie", "command": "python3", "args": ["-m", "agentdemo", "mcp"]},
                    {"name": "git", "command": "npx", "args": ["-y", "server-git"], "enabled": False},
                ]
            }
        )
        settings.save(path)
        reloaded = Settings.load(path)
        self.assertEqual([srv.name for srv in reloaded.mcp_servers], ["vigie", "git"])
        self.assertFalse(reloaded.mcp_servers[1].enabled)
        public = reloaded.as_public()
        self.assertEqual(len(public["mcp_servers"]), 2)
        self.assertIn("args", public["mcp_servers"][0])

        bad = Settings()
        with self.assertRaises(ValueError):
            bad.update({"mcp_servers": [{"name": "mauvais nom!", "command": "python3"}]})
        with self.assertRaises(ValueError):
            bad.update({"mcp_servers": [{"name": "ok", "command": "python3", "args": ["../../etc/passwd"]}]})

    def test_tool_install_verifies_hash_and_traversal(self) -> None:
        import os
        import shutil as sh

        from agentdemo import toolcatalog

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        source = root / "catalogue" / "csv_top"
        source.mkdir(parents=True)
        template = Path(toolcatalog.CATALOG_DIR) / "csv_top"
        for name in ("manifest.json", "csv_top.py"):
            sh.copy2(template / name, source / name)

        with self.assertRaises(toolcatalog.CatalogError):
            toolcatalog.install(root, str(source), approved=False)

        installed = toolcatalog.install(root, str(source), approved=True)
        self.assertEqual(installed["name"], "csv_top")
        self.assertEqual(len(toolcatalog.installed(root)), 1)

        # empreinte falsifiée
        tampered = root / "catalogue" / "faux"
        sh.copytree(source, tampered)
        (tampered / "csv_top.py").write_text("def main(**kwargs):\n    return 'pirate'\n", encoding="utf-8")
        with self.assertRaises(toolcatalog.CatalogError):
            toolcatalog.install(root, str(tampered), approved=True, force=True)

        # point d'entrée qui sort du dossier
        escape = root / "catalogue" / "evasion"
        escape.mkdir()
        import json as _json

        manifest = _json.loads((source / "manifest.json").read_text())
        manifest["entrypoint"] = "../../etc/passwd"
        (escape / "manifest.json").write_text(_json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(toolcatalog.CatalogError):
            toolcatalog.install(root, str(escape), approved=True)

    def test_mcp_server_lists_and_calls_tools(self) -> None:
        """Un client MCP liste les outils et en exécute un, sans planter."""
        import json as _json
        import os
        import subprocess

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "ws"
        workspace.mkdir()
        (workspace / "note.txt").write_text("contenu", encoding="utf-8")
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "fs_write", "arguments": {"path": "sortie.txt", "content": "ok"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "mail_list", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "inconnue/vraiment"},
        ]
        payload = "\n".join(_json.dumps(m) for m in messages) + "\n"
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
        completed = subprocess.run(
            [sys.executable, "-c",
             f"from pathlib import Path; from agentdemo.mcp_server import serve_stdio; "
             f"serve_stdio(Path({str(workspace)!r}), Path({str(root)!r}))"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        responses = [_json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        self.assertGreaterEqual(len(responses), 4)
        listed = next(r for r in responses if r.get("id") == 2)["result"]["tools"]
        names = {tool["name"] for tool in listed}
        self.assertIn("fs_read", names)
        self.assertNotIn("mail_list", names, "les outils d'écriture et de réseau ne sont pas exposés")
        self.assertIn("inputSchema", listed[0])
        written = next(r for r in responses if r.get("id") == 3)
        self.assertFalse(written["result"]["isError"])
        self.assertTrue((workspace / "sortie.txt").exists())
        refused = next(r for r in responses if r.get("id") == 4)
        self.assertIn("error", refused)
        self.assertEqual(refused["error"]["code"], -32602)
        unknown = next(r for r in responses if r.get("id") == 5)
        self.assertEqual(unknown["error"]["code"], -32601)

    def test_routing_resolution_order(self) -> None:
        """Forçage manuel > règle > défaut, et les règles s'évaluent dans l'ordre."""
        from agentdemo.routing import RoutingTable, Rule, Target

        table = RoutingTable(
            targets=[
                Target("local-a", "petit", "http://localhost:1234/v1", "petit"),
                Target("local-b", "gros", "http://localhost:1234/v1", "gros"),
                Target("cloud", "cloud", "https://api.exemple.invalid/v1", "gros-cloud", "cloud"),
            ],
            rules=[
                Rule("sensitive", "", "local-b", "données sensibles en local"),
                Rule("scenario", "dataset-report", "cloud", "analyse non sensible"),
                Rule("keyword", r"r[ée]sum", "local-a", "tâche mécanique"),
                Rule("always", "", "local-b", "défaut"),
            ],
            default_target="local-b",
        )
        self.assertEqual(table.resolve("Résume le dossier").target.id, "local-a")
        self.assertEqual(table.resolve("Analyse ce jeu de données", "dataset-report").target.id, "cloud")
        self.assertEqual(table.resolve("Résume le dossier client").target.id, "local-b", "sensible passe avant")
        self.assertEqual(table.resolve("Écris un poème").target.id, "local-b")

        table.override = "cloud"
        self.assertEqual(table.resolve("Résume le dossier client").target.id, "cloud", "le forçage prime")
        self.assertEqual(table.resolve("Résume").matched, "override")

    def test_routing_rejects_a_broken_policy(self) -> None:
        from agentdemo.routing import RoutingError, RoutingTable, Rule, Target

        table = RoutingTable(targets=[Target("a", "A", "http://localhost:1234/v1", "m")], default_target="a")
        with self.assertRaises(RoutingError):
            table.set_rules([Rule("keyword", "(", "a")])  # expression invalide
        with self.assertRaises(RoutingError):
            table.set_rules([Rule("scenario", "x", "absente")])  # cible inconnue
        with self.assertRaises(RoutingError):
            table.remove_target("a")  # cible par défaut retirée sans repli

    def test_routing_round_trip(self) -> None:
        import json
        from agentdemo.routing import RoutingTable

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "routing.json"
        table = RoutingTable.default()
        table.override = "cloud"
        table.record(table.resolve("test"), "test")
        table.save(path)
        reloaded = RoutingTable.load(path)
        self.assertEqual(reloaded.override, "cloud")
        self.assertEqual(len(reloaded.targets), len(table.targets))
        self.assertEqual(len(reloaded.history), 1)
        self.assertIn("targets", json.loads(path.read_text(encoding="utf-8")))

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
