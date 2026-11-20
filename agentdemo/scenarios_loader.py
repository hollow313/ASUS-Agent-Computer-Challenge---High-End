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
    passes: list[dict[str, Any]]

    def cassette(self, index: int = 0) -> list[dict[str, Any]]:
        """Recorded trace of pass ``index`` (a scenario can be replayed twice to
        show what the agent learned between two runs)."""
        passes = self.passes or [{"label": "", "cassette": "cassette.json"}]
        name = passes[min(index, len(passes) - 1)].get("cassette", "cassette.json")
        path = self.root / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def pass_labels(self) -> list[str]:
        return [p.get("label", "") for p in (self.passes or [{"label": ""}])]

    def apply_mutations(self, index: int, workspace: Path) -> list[str]:
        """Applique les modifications prévues avant une passe (renommage, déplacement).

        Sert à démontrer qu'une procédure peut devenir fausse : le fichier sur lequel elle
        s'appuie est renommé entre deux passes, le contrat de vérification casse.
        """
        passes = self.passes or [{"label": ""}]
        entry = passes[min(index, len(passes) - 1)]
        applied = []
        for move in entry.get("mutate", {}).get("move", []):
            source, dest = workspace / move[0], workspace / move[1]
            if source.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                source.replace(dest)
                applied.append(f"{move[0]} -> {move[1]}")
        return applied

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
            "passes": self.pass_labels(),
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
                passes=list(meta.get("passes", [{"label": "", "cassette": "cassette.json"}])),
            )
        )
    return scenarios


def get_scenario(slug: str) -> Scenario:
    for scenario in list_scenarios():
        if scenario.slug == slug:
            return scenario
    raise KeyError(f"scénario inconnu : {slug}")
