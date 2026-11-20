"""Mémoire procédurale, avec un cycle de vie honnête.

Une procédure n'est pas une vérité : c'est une hypothèse qui peut devenir fausse (un fichier
renommé, une API qui change, un sélecteur qui ne matche plus). Ce module gère quatre choses :

* **provenance** : chaque procédure porte son compteur d'usages, ses succès et ses échecs ;
* **contrat de vérification** : une procédure peut déclarer `check: path_exists chemin`, rejoué à
  chaque rappel. Si le contrat casse, la procédure est marquée `stale` et n'est plus servie ;
* **score de confiance** : (succès + 1) / (usages + 2), lissage de Laplace, affiché en pourcentage ;
* **mise à la retraite réversible** : une procédure stale, ou de confiance trop basse et assez
  utilisée, est déplacée dans `retired/`, jamais supprimée.

Le format sur disque reste du markdown lisible, avec un en-tête de métadonnées :

    ---
    uses: 3
    success: 2
    failure: 1
    status: active
    check: path_exists feeds/flux-avis-112026.xml
    last_used: 2026-11-20
    ---
    # Procédure, flux d'avis dans feeds/
    ...
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

META_KEYS = ("uses", "success", "failure", "status", "check", "created", "last_used", "retired")
STALE_AFTER_DAYS = int(os.environ.get("AGENTDEMO_SKILL_STALE_DAYS", "30"))


@dataclass
class Skill:
    name: str
    meta: dict[str, str] = field(default_factory=dict)
    body: str = ""
    path: Path | None = None

    @property
    def uses(self) -> int:
        return _as_int(self.meta.get("uses"))

    @property
    def successes(self) -> int:
        return _as_int(self.meta.get("success"))

    @property
    def failures(self) -> int:
        return _as_int(self.meta.get("failure"))

    @property
    def status(self) -> str:
        return self.meta.get("status", "active")

    @property
    def confidence(self) -> float:
        """Lissage de Laplace : une procédure jamais utilisée part à 50 %, pas à 100 %."""
        return (self.successes + 1) / (self.uses + 2)

    @property
    def check(self) -> str:
        return self.meta.get("check", "").strip()

    @property
    def summary(self) -> str:
        for line in self.body.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:120]
        return ""

    def as_row(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "uses": self.uses,
            "success": self.successes,
            "failure": self.failures,
            "confidence": round(100 * self.confidence),
            "check": self.check,
            "summary": self.summary,
            "last_used": self.meta.get("last_used", ""),
        }


def _as_int(value: str | None) -> int:
    try:
        return int(str(value or "0").strip())
    except ValueError:
        return 0


def parse(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    header, body = text[4:end], text[end + 5 :]
    meta: dict[str, str] = {}
    for line in header.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, body


def render(meta: dict[str, str], body: str) -> str:
    ordered = [(key, meta[key]) for key in META_KEYS if key in meta]
    ordered += [(key, value) for key, value in meta.items() if key not in META_KEYS]
    header = "\n".join(f"{key}: {value}" for key, value in ordered)
    return f"---\n{header}\n---\n{body.strip()}\n"


class SkillStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.retired_dir = self.root / "retired"
        self.retired_dir.mkdir(parents=True, exist_ok=True)

    # ---------- lecture ----------
    def _path(self, name: str) -> Path:
        safe = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "skill"
        return self.root / f"{safe}.md"

    def get(self, name: str) -> "Skill | None":
        path = self._path(name)
        if not path.exists():
            return None
        meta, body = parse(path.read_text(encoding="utf-8"))
        return Skill(path.stem, meta, body, path)

    def list(self, include_retired: bool = False) -> list[Skill]:
        skills = []
        for path in sorted(self.root.glob("*.md")):
            meta, body = parse(path.read_text(encoding="utf-8"))
            skills.append(Skill(path.stem, meta, body, path))
        if include_retired:
            for path in sorted(self.retired_dir.glob("*.md")):
                meta, body = parse(path.read_text(encoding="utf-8"))
                meta.setdefault("status", "retired")
                skills.append(Skill(path.stem, meta, body, path))
        return skills

    # ---------- contrat de vérification ----------
    def verify(self, skill: Skill, sandbox: "Path | None" = None) -> tuple[bool, str]:
        """Rejoue le contrat déclaré par la procédure. Retourne (valide, message)."""
        claim = skill.check
        if not claim:
            return True, "aucun contrat déclaré"
        kind, _, argument = claim.partition(" ")
        argument = argument.strip()
        if kind != "path_exists":
            return False, f"contrat inconnu : {kind}"
        root = Path(sandbox) if sandbox else self.root
        target = (root / argument).resolve()
        if root.resolve() not in target.parents and target != root.resolve():
            return False, f"chemin hors périmètre dans le contrat : {argument}"
        exists = target.exists()
        return exists, f"{argument} {'présent' if exists else 'introuvable'}"

    # ---------- rappel ----------
    def recall(self, keyword: str = "", sandbox: "Path | None" = None) -> list[Skill]:
        """Rappelle les procédures valides ; celles dont le contrat casse sont écartées."""
        keyword = (keyword or "").strip().lower()
        selected = [
            skill
            for skill in self.list()
            if skill.status == "active"
            and (not keyword or keyword in skill.body.lower() or keyword in skill.name.lower())
        ]
        valid: list[Skill] = []
        for skill in selected:
            ok, message = self.verify(skill, sandbox)
            if ok:
                valid.append(skill)
                self._touch(skill)
            else:
                self._retire(skill, f"contrat invalide : {message}")
        return valid

    def format_recall(self, keyword: str = "", sandbox: "Path | None" = None) -> str:
        found = self.recall(keyword, sandbox)
        if not found:
            return (
                f"aucune procédure valide pour « {keyword or '*'} » "
                "(absente, ou contrat de vérification cassé donc mise à la retraite)"
            )
        blocks = [
            f"### {skill.name} (confiance {round(100 * skill.confidence)} %)\n{skill.body.strip()}"
            for skill in found
        ]
        return "\n\n".join(blocks)

    # ---------- écriture ----------
    def write(self, name: str, content: str, check: str = "") -> Skill:
        path = self._path(name)
        today = date.today().isoformat()
        existing = self.get(name)
        meta = dict(existing.meta) if existing else {"created": today}
        meta.setdefault("uses", "0")
        meta.setdefault("success", "0")
        meta.setdefault("failure", "0")
        meta["status"] = "active"
        meta.setdefault("last_used", today)
        if check:
            meta["check"] = check
        path.write_text(render(meta, content), encoding="utf-8")
        written = self.get(name)
        assert written is not None
        return written

    def feedback(self, name: str, ok: bool) -> "Skill | None":
        skill = self.get(name)
        if not skill or not skill.path:
            return None
        skill.meta["uses"] = str(skill.uses + 1)
        skill.meta["success" if ok else "failure"] = str(
            (skill.successes + 1) if ok else (skill.failures + 1)
        )
        skill.meta["last_used"] = date.today().isoformat()
        if not ok and skill.failures >= 2 and skill.confidence < 0.4:
            skill.meta["status"] = "stale"
        skill.path.write_text(render(skill.meta, skill.body), encoding="utf-8")
        return self.get(name)

    def prune(self, min_confidence: float = 0.35, min_uses: int = 2) -> list[str]:
        """Met à la retraite ce qui est stale, ou peu fiable et assez utilisé. Jamais de suppression."""
        retired = []
        for skill in self.list():
            if skill.status == "stale" or (
                skill.uses >= min_uses and skill.confidence < min_confidence
            ):
                self._retire(skill, f"confiance {round(100 * skill.confidence)} % sur {skill.uses} usages")
                retired.append(skill.name)
            elif self._idle_too_long(skill):
                self._retire(skill, f"inutilisée depuis plus de {STALE_AFTER_DAYS} jours")
                retired.append(skill.name)
        return retired

    # ---------- interne ----------
    def _touch(self, skill: Skill) -> None:
        skill.meta["last_used"] = date.today().isoformat()
        if skill.path:
            skill.path.write_text(render(skill.meta, skill.body), encoding="utf-8")

    def _retire(self, skill: Skill, reason: str) -> None:
        if not skill.path or not skill.path.exists():
            return
        skill.meta["status"] = "stale"
        skill.meta["retired"] = f"{date.today().isoformat()} ({reason})"
        skill.path.write_text(render(skill.meta, skill.body), encoding="utf-8")
        shutil.move(str(skill.path), str(self.retired_dir / skill.path.name))

    def _idle_too_long(self, skill: Skill) -> bool:
        raw = skill.meta.get("last_used", "")
        if not raw:
            return False
        try:
            last = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return False
        return (date.today() - last).days > STALE_AFTER_DAYS

    def ledger(self) -> list[dict]:
        return [skill.as_row() for skill in self.list(include_retired=True)]
