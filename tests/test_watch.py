"""Déclencheurs : un dossier surveillé, un verrou, et rien qui se déclenche soi-même."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from agentdemo.watch import acquire, deliver, release, should_handle, stable


class WatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()

    def test_lock_prevents_two_runs_at_once(self) -> None:
        self.assertTrue(acquire(self.data))
        self.assertFalse(acquire(self.data), "un second run ne doit pas prendre le verrou")
        release(self.data)
        self.assertTrue(acquire(self.data), "après libération, le verrou est de nouveau disponible")
        release(self.data)

    def test_stale_lock_is_reclaimed(self) -> None:
        self.assertTrue(acquire(self.data))
        lock = self.data / ".vigie.lock"
        old = time.time() - 7 * 3600
        import os

        os.utime(lock, (old, old))
        self.assertTrue(acquire(self.data), "un verrou de sept heures est repris")
        release(self.data)

    def test_output_directory_is_never_watched(self) -> None:
        produced = self.data / "runs" / "x" / "workspace" / "briefing.md"
        produced.parent.mkdir(parents=True)
        produced.write_text("contenu", encoding="utf-8")
        self.assertFalse(should_handle(produced, self.data, set()), "l'agent ne doit pas se déclencher sur sa sortie")

    def test_hidden_and_empty_files_are_ignored(self) -> None:
        hidden = self.inbox / ".cache"
        hidden.write_text("x", encoding="utf-8")
        empty = self.inbox / "vide.eml"
        empty.write_text("", encoding="utf-8")
        real = self.inbox / "message.eml"
        real.write_text("De: a@b.fr", encoding="utf-8")
        self.assertFalse(should_handle(hidden, self.data, set(), self.inbox))
        self.assertFalse(should_handle(empty, self.data, set(), self.inbox))
        self.assertTrue(should_handle(real, self.data, set(), self.inbox))

    def test_file_still_being_written_is_not_stable(self) -> None:
        path = self.inbox / "gros.eml"
        path.write_text("a" * 10, encoding="utf-8")

        def grow() -> None:
            with path.open("a", encoding="utf-8") as handle:
                handle.write("b" * 50)

        import threading

        timer = threading.Timer(0.2, grow)
        timer.start()
        self.assertFalse(stable(path, delay=1.0), "un fichier qui grossit n'est pas prêt")
        timer.join()
        self.assertTrue(stable(path, delay=0.2))

    def test_deliver_copies_without_touching_the_original(self) -> None:
        source = self.inbox / "message.eml"
        source.write_text("De: a@b.fr", encoding="utf-8")
        staged = deliver(source, self.data / "watch-inputs")
        self.assertTrue(staged.exists())
        self.assertEqual(staged.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
        self.assertTrue(source.exists(), "l'original reste en place")


if __name__ == "__main__":
    unittest.main()


class BootstrapTimingTests(unittest.TestCase):
    def test_imposed_steps_report_a_positive_duration(self) -> None:
        """Une durée négative dans le journal, c'est un chrono mal pris : le signe se teste."""
        import json
        import tempfile
        from pathlib import Path as _Path

        from agentdemo.agent import Agent
        from agentdemo.tools import Sandbox, build_registry

        class Planner:
            label = "scripted"

            def next_action(self, objective, history):
                return {"thought": "fini", "final": "ok"}

        with tempfile.TemporaryDirectory() as tmp:
            workspace = _Path(tmp) / "ws"
            workspace.mkdir()
            (workspace / "note.txt").write_text("bonjour", encoding="utf-8")
            agent = Agent(
                planner=Planner(),
                workspace=workspace,
                runs_dir=_Path(tmp) / "runs",
                max_steps=3,
                scenario="chrono",
                bootstrap=[{"tool": "fs_list", "args": {"path": "."}, "thought": "étape imposée"}],
            )
            result = agent.run("objectif", run_id="chrono")
        imposed = result.steps[0]
        self.assertEqual(imposed.tool, "fs_list")
        self.assertGreaterEqual(imposed.duration_ms, 0, "une durée négative veut dire un chrono mélangé")
        self.assertLess(imposed.duration_ms, 60_000)
