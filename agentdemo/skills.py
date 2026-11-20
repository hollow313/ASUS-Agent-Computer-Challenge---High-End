"""Persistent procedural memory ("skills").

This is the smallest honest version of what the production agent does: when a run
hits a wall, the agent writes the lesson as a markdown procedure, and the next run
recalls it *before* acting. The store lives outside the run sandbox, so it survives
across runs, which is exactly the point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    content: str

    @property
    def summary(self) -> str:
        for line in self.content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:120]
        return ""


class SkillStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        safe = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "skill"
        return self.root / f"{safe}.md"

    def list(self) -> list[Skill]:
        skills = []
        for path in sorted(self.root.glob("*.md")):
            skills.append(Skill(path.stem, path.read_text(encoding="utf-8")))
        return skills

    def recall(self, keyword: str = "") -> list[Skill]:
        keyword = (keyword or "").strip().lower()
        if not keyword:
            return self.list()
        return [s for s in self.list() if keyword in s.content.lower() or keyword in s.name.lower()]

    def write(self, name: str, content: str) -> Path:
        path = self._path(name)
        path.write_text(content.strip() + "\n", encoding="utf-8")
        return path

    def format_recall(self, keyword: str = "") -> str:
        found = self.recall(keyword)
        if not found:
            return (
                f"aucune procédure enregistrée pour « {keyword or '*'} », "
                "c'est la première fois, j'apprendrai de ce run"
            )
        blocks = [f"### {skill.name}\n{skill.content.strip()}" for skill in found]
        return "\n\n".join(blocks)
