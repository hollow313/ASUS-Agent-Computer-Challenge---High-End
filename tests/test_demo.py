"""Smoke tests: the three scenarios run end to end, in a temporary workspace.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

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
        self.assertIn("trois fois", result.summary.lower())

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
