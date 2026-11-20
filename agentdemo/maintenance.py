"""Entretien automatique de la mémoire procédurale.

Le principe : ce que l'agent apprend doit pouvoir vieillir sans lui. Un mainteneur tourne
périodiquement, sans intervention, et fait trois choses :

1. **réparation** : une procédure dont le contrat `path_exists` casse est réparée si la cible a
   simplement été renommée ou déplacée. Le mainteneur cherche un candidat crédible dans le bac à
   sable, réécrit le contrat, et ne réactive la procédure que si le nouveau contrat passe ;
2. **arbitrage par preuve** : deux procédures du même sujet ne sont plus départagées à la seule
   confiance. Si l'une a un contrat qui passe et l'autre non, la preuve tranche avant le score ;
3. **retrait** : ce qui reste faux, peu fiable ou dormant part en retraite, jamais à la poubelle.

Tout est journalisé dans `maintenance.jsonl`, une ligne JSON par passe, pour être audité.
"""

from __future__ import annotations

import difflib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .skills import Skill, SkillStore


@dataclass
class MaintenanceReport:
    repaired: list[dict[str, str]] = field(default_factory=list)
    superseded: list[dict[str, str]] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    scanned: int = 0
    started_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "scanned": self.scanned,
            "repaired": self.repaired,
            "superseded": self.superseded,
            "retired": self.retired,
        }

    @property
    def changed(self) -> bool:
        return bool(self.repaired or self.superseded or self.retired)


class Maintainer:
    def __init__(self, skills: SkillStore, sandbox: Path, log_path: Path | None = None) -> None:
        self.skills = skills
        self.sandbox = Path(sandbox)
        self.log_path = Path(log_path) if log_path else self.skills.root.parent / "maintenance.jsonl"

    # ---------- passe complète ----------
    def run_once(self) -> MaintenanceReport:
        report = MaintenanceReport(
            started_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        active = self.skills.list()
        report.scanned = len(active)

        # 1) réparer ce qui peut l'être, récupérer ce qui était en retraite
        active_names = {skill.name for skill in active}
        pool = active + [
            skill for skill in self.skills.list(include_retired=True) if skill.name not in active_names
        ]
        seen: set[str] = set()
        for skill in pool:
            if skill.name in seen:
                continue
            seen.add(skill.name)
            ok, message = self.skills.verify(skill, self.sandbox)
            if ok:
                continue
            repair = self._repair(skill, message)
            if repair:
                report.repaired.append(repair)

        # 2) arbitrer par preuve, puis par confiance
        report.superseded = self._arbitrate()

        # 3) retraite de ce qui est faux, dormant ou peu fiable
        report.retired = self.skills.prune()

        self._log(report)
        return report

    # ---------- réparation ----------
    def _repair(self, skill: Skill, message: str) -> dict[str, str] | None:
        claim = skill.check
        if not claim.startswith("path_exists "):
            return None
        missing = claim.split(" ", 1)[1].strip()
        candidate = self._find_candidate(Path(missing).name)
        if candidate is None:
            return None
        new_check = f"path_exists {candidate}"
        body = skill.body.replace(missing, candidate)
        revised = self.skills.revise(
            skill.name, body, new_check, reason=f"cible renommée : {missing} -> {candidate} ({message})"
        )
        if revised is None or revised.status != "active":
            return None
        return {"procedure": revised.name, "de": missing, "vers": candidate}

    def _find_candidate(self, missing_name: str) -> str | None:
        """Cherche un fichier du bac à sable qui ressemble au nom disparu."""
        stem = Path(missing_name).stem
        suffix = Path(missing_name).suffix
        best: tuple[float, Path] | None = None
        for path in sorted(self.sandbox.rglob("*")):
            if not path.is_file() or path.name == missing_name:
                continue
            if path.suffix and suffix and path.suffix != suffix:
                continue
            score = difflib.SequenceMatcher(None, stem, path.stem).ratio()
            if score < 0.6:
                continue
            if best is None or score > best[0]:
                best = (score, path)
        if best is None:
            return None
        return str(best[1].relative_to(self.sandbox))

    # ---------- arbitrage ----------
    def _arbitrate(self) -> list[dict[str, str]]:
        """La preuve d'abord : entre deux procédures du même sujet, celle qui se vérifie gagne."""
        groups: dict[str, list[Skill]] = {}
        for skill in self.skills.list():
            key = skill.meta.get("topic", "").strip().lower() or skill.name
            groups.setdefault(key, []).append(skill)

        decisions: list[dict[str, str]] = []
        for topic, skills in groups.items():
            if len(skills) < 2:
                continue
            verdict = []
            for skill in skills:
                ok, _ = self.skills.verify(skill, self.sandbox)
                verdict.append((ok, skill))
            verified = [skill for ok, skill in verdict if ok]
            broken = [skill for ok, skill in verdict if not ok]
            if verified and broken:
                winner = max(verified, key=lambda s: s.confidence)
                for loser in broken:
                    if not loser.path:
                        continue
                    loser.meta["status"] = "superseded"
                    loser.meta["superseded_by"] = winner.name
                    loser.meta["retired"] = (
                        f"{datetime.now(timezone.utc).date().isoformat()} "
                        "(contrat cassé, arbitré par la preuve)"
                    )
                    loser.path.write_text(_render(loser.meta, loser.body), encoding="utf-8")
                    decisions.append(
                        {"topic": topic, "winner": winner.name, "loser": loser.name, "reason": "preuve"}
                    )
        # puis les conflits sans preuve : la confiance tranche
        for item in self.skills.resolve_conflicts():
            decisions.append({**item, "reason": "confiance"})
        return decisions

    # ---------- journal ----------
    def _log(self, report: MaintenanceReport) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report.as_dict(), ensure_ascii=False) + "\n")

    # ---------- boucle ----------
    def loop(self, interval: int = 60, max_passes: int | None = None, on_report=None) -> None:
        passes = 0
        while max_passes is None or passes < max_passes:
            report = self.run_once()
            if on_report is not None:
                on_report(report)
            passes += 1
            time.sleep(interval)


def _render(meta: dict[str, str], body: str) -> str:
    from .skills import render

    return render(meta, body)
