"""Consigne libre : les garde-fous sont dans le code, pas dans le prompt."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentdemo.agent import Agent
from agentdemo.ask import (
    MAX_CHARS,
    AskError,
    build,
    enforce_deliverable,
    network_for,
    slug_for,
    validate,
)
from agentdemo.tools import Sandbox, ToolError


class ScriptedPlanner:
    """Un planificateur qui récite : sert à prouver la boucle, pas la qualité du modèle."""

    def __init__(self, actions: list[dict]):
        self.actions = actions
        self.index = 0
        self.label = "scripted"

    def next_action(self, objective: str, history: list[dict]) -> dict:
        if self.index >= len(self.actions):
            return {"thought": "fini", "final": "rien de plus"}
        action = self.actions[self.index]
        self.index += 1
        return action


class AskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_empty_objective_is_refused(self) -> None:
        with self.assertRaises(AskError) as caught:
            validate("   ")
        self.assertIn("vide", str(caught.exception))

    def test_long_objective_is_refused_with_the_limit(self) -> None:
        with self.assertRaises(AskError) as caught:
            validate("a" * 700)
        message = str(caught.exception)
        self.assertIn(str(MAX_CHARS), message)
        self.assertIn("700", message)
        self.assertIn("scénario", message)

    def test_same_objective_gives_the_same_slug(self) -> None:
        """Le slug vient du texte normalisé : sans ça, --resume ne retrouve rien."""
        first = slug_for("Classe les trois CSV et écris un comparatif")
        second = slug_for("  classe  les trois csv et écris un comparatif ")
        third = slug_for("résume le dossier autrement")
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertTrue(first.startswith("ask-"))
        self.assertEqual(len(first), len("ask-") + 8)

    def test_network_defaults_to_deny_and_builds_allowlist(self) -> None:
        self.assertEqual(network_for(), {"mode": "deny", "hosts": []})
        allowed = network_for(["a.fr", "b.fr"])
        self.assertEqual(allowed["mode"], "allowlist")
        self.assertEqual(allowed["hosts"], ["a.fr", "b.fr"])

    def test_open_network_needs_a_confirmation(self) -> None:
        with self.assertRaises(AskError) as caught:
            network_for(allow_open=True)
        self.assertIn("--yes", str(caught.exception))
        self.assertEqual(network_for(allow_open=True, confirmed=True)["mode"], "open")

    def test_run_without_any_file_is_blocked_not_done(self) -> None:
        workspace = self.root / "runs" / "ask-test" / "workspace"
        workspace.mkdir(parents=True)
        planner = ScriptedPlanner([{"thought": "je réponds", "final": "voici ce que je ferais"}])
        agent = Agent(
            planner=planner,
            workspace=workspace,
            runs_dir=self.root / "runs",
            max_steps=4,
            scenario="ask-test",
        )
        result = agent.run("écris un résumé", run_id="ask-test")
        self.assertEqual(result.status, "done", "l'agent, lui, a bien répondu")
        enforce_deliverable(result)
        self.assertEqual(result.status, "blocked", "sans fichier écrit, ce n'est pas un livrable")
        self.assertIn("Aucun fichier écrit", result.summary)

    def test_run_with_a_file_exposes_the_artifact_and_the_journal(self) -> None:
        workspace = self.root / "runs" / "ask-ok" / "workspace"
        workspace.mkdir(parents=True)
        planner = ScriptedPlanner(
            [
                {
                    "thought": "j'écris le livrable",
                    "tool": "fs_write",
                    "args": {"path": "reponse.md", "content": "# Réponse\n\nTrois fichiers classés.\n"},
                },
                {"thought": "c'est écrit", "final": "reponse.md écrit"},
            ]
        )
        agent = Agent(
            planner=planner,
            workspace=workspace,
            runs_dir=self.root / "runs",
            max_steps=4,
            scenario="ask-ok",
        )
        result = agent.run("écris un résumé", run_id="ask-ok")
        enforce_deliverable(result)
        self.assertEqual(result.status, "done")
        self.assertIn("reponse.md", result.artifacts)
        journal = self.root / "runs" / "ask-ok.json"
        self.assertTrue(journal.exists())
        payload = json.loads(journal.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(payload.get("steps") or []), 2)

    def test_writing_outside_the_workspace_is_refused(self) -> None:
        workspace = self.root / "runs" / "ask-jail" / "workspace"
        workspace.mkdir(parents=True)
        sandbox = Sandbox(workspace)
        with self.assertRaises(ToolError):
            sandbox.resolve("../evasion.txt")

    def test_build_returns_an_ephemeral_scenario_without_cassette(self) -> None:
        scenario = build("classe les fichiers et écris un comparatif", data_dir=self.root)
        self.assertEqual(scenario.tags, ["ask"])
        self.assertEqual(scenario.network["mode"], "deny")
        self.assertEqual(scenario.max_steps, 14)
        self.assertEqual(scenario.pass_labels(), ["consigne libre"])
        self.assertFalse(scenario.has_cassette())


if __name__ == "__main__":
    unittest.main()
