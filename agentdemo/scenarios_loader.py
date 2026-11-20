"""Scenario loading: metadata, recorded decision trace, fixture files."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


@dataclass
class Scenario:
    slug: str
    title: str
    blurb: str
    objective: str
    max_steps: int
    tags: list[str]
    root: Path

    def cassette(self) -> list[dict[str, Any]]:
        path = self.root / "cassette.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def stage(self, workspace: Path) -> None:
        """Copy the scenario fixtures into the run workspace."""
        fixtures = self.root / "fixtures"
        if not fixtures.exists():
            return
        for item in fixtures.iterdir():
            destination = workspace / item.name
            if item.is_dir():
                shutil.copytree(item, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(item, destination)

    def as_summary(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "blurb": self.blurb,
            "objective": self.objective,
            "tags": self.tags,
            "steps": len(self.cassette()),
        }


def list_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []
    if not SCENARIOS_DIR.exists():
        return scenarios
    for folder in sorted(SCENARIOS_DIR.iterdir()):
        meta_file = folder / "scenario.json"
        if not (folder.is_dir() and meta_file.exists()):
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        scenarios.append(
            Scenario(
                slug=meta["slug"],
                title=meta["title"],
                blurb=meta.get("blurb", ""),
                objective=meta["objective"],
                max_steps=int(meta.get("max_steps", 14)),
                tags=list(meta.get("tags", [])),
                root=folder,
            )
        )
    return scenarios


def get_scenario(slug: str) -> Scenario:
    for scenario in list_scenarios():
        if scenario.slug == slug:
            return scenario
    raise KeyError(f"scénario inconnu : {slug}")
