"""Sandboxed tools available to the agent.

Every tool operates inside a single run workspace directory and refuses to touch
anything outside it. Tool results are returned as short human-readable strings:
that is exactly what the model sees as an observation.
"""

from __future__ import annotations

import csv
import os
import shutil
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MAX_OBSERVATION_CHARS = 2400
NETWORK_ENABLED = os.environ.get("AGENTDEMO_ALLOW_NETWORK", "0") == "1"


class ToolError(RuntimeError):
    """Raised when a tool cannot complete. The message is fed back to the model."""


@dataclass(frozen=True)
class Tool:
    name: str
    signature: str
    description: str
    fn: Callable[..., str]


def _clip(text: str, limit: int = MAX_OBSERVATION_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [{len(text) - limit} caractères tronqués]"


class Sandbox:
    """Constrains every path to the run workspace."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative: str) -> Path:
        candidate = (self.root / str(relative)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ToolError(f"chemin hors du bac à sable refusé : {relative}")
        return candidate

    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.root))


def build_registry(sandbox: Sandbox, artifacts: list[str], skills: "SkillStore | None" = None) -> dict[str, Tool]:
    """Return the tool registry bound to one sandbox (and, optionally, a skill store)."""

    def note(path: Path) -> None:
        name = sandbox.rel(path)
        if name not in artifacts:
            artifacts.append(name)

    def skill_list() -> str:
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        found = skills.list()
        if not found:
            return "aucune procédure enregistrée"
        return "\n".join(f"- {s.name} : {s.summary}" for s in found)

    def skill_recall(keyword: str = "") -> str:
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        return skills.format_recall(keyword)

    def skill_write(name: str, content: str) -> str:
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        path = skills.write(name, content)
        return f"procédure « {path.stem} » enregistrée ({len(content)} caractères) — réutilisable aux runs suivants"

    def fs_list(path: str = ".") -> str:
        target = sandbox.resolve(path)
        if not target.exists():
            raise ToolError(f"introuvable : {path}")
        if target.is_file():
            return f"{path} est un fichier ({target.stat().st_size} octets)"
        rows = []
        for entry in sorted(target.iterdir()):
            kind = "dir " if entry.is_dir() else "file"
            size = "" if entry.is_dir() else f"  {entry.stat().st_size:>7} o"
            rows.append(f"{kind}  {entry.name}{size}")
        return "\n".join(rows) or "(dossier vide)"

    def fs_read(path: str, max_chars: int = 4000) -> str:
        target = sandbox.resolve(path)
        if not target.is_file():
            raise ToolError(f"fichier introuvable : {path}")
        text = target.read_text(encoding="utf-8", errors="replace")
        head = text[: int(max_chars)]
        if len(text) > len(head):
            head += f"\n… [{len(text) - len(head)} caractères non affichés]"
        return f"# {path} ({len(text)} caractères)\n{head}"

    def fs_write(path: str, content: str) -> str:
        target = sandbox.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        note(target)
        return f"écrit {path} — {target.stat().st_size} octets"

    def fs_move(src: str, dst: str) -> str:
        source, dest = sandbox.resolve(src), sandbox.resolve(dst)
        if not source.exists():
            raise ToolError(f"source introuvable : {src}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        return f"déplacé {src} → {dst}"

    def csv_profile(path: str) -> str:
        target = sandbox.resolve(path)
        if not target.is_file():
            raise ToolError(f"csv introuvable : {path}")
        with target.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            return "aucune ligne de données"
        columns = list(rows[0].keys())
        numeric = [c for c in columns if all(_is_number(r.get(c)) for r in rows)]
        lines = [f"{len(rows)} lignes, {len(columns)} colonnes", f"colonnes : {', '.join(columns)}"]
        for column in numeric:
            values = [float(r[column]) for r in rows]
            lines.append(
                f"{column}: min={min(values):.2f} max={max(values):.2f} "
                f"total={sum(values):.2f} moyenne={sum(values) / len(values):.2f}"
            )
        return "\n".join(lines)

    def chart_bar(path: str, label_column: str, value_column: str, output: str, title: str = "Graphique") -> str:
        target = sandbox.resolve(path)
        if not target.is_file():
            raise ToolError(f"csv introuvable : {path}")
        with target.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        series = [(r[label_column], float(r[value_column])) for r in rows if _is_number(r.get(value_column))]
        if not series:
            raise ToolError("aucune valeur numérique exploitable")
        dest = sandbox.resolve(output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_bar_svg(series, title, value_column), encoding="utf-8")
        note(dest)
        return f"graphique écrit dans {output} ({len(series)} barres)"

    def rss_rank(paths: list[str], top_n: int = 6) -> str:
        items: list[tuple[str, str, str]] = []
        for raw in paths:
            target = sandbox.resolve(raw)
            if not target.is_file():
                raise ToolError(f"flux introuvable : {raw}")
            try:
                root = ET.fromstring(target.read_text(encoding="utf-8", errors="replace"))
            except ET.ParseError as exc:
                raise ToolError(f"XML invalide dans {raw} : {exc}") from exc
            for node in root.iter("item"):
                title = (node.findtext("title") or "").strip()
                summary = (node.findtext("description") or "").strip()
                items.append((title, summary, target.name))
        scored = sorted(((len(summary), t, s, f) for t, s, f in items), reverse=True)
        lines = [f"{len(items)} entrées lues dans {len(paths)} flux, classées par densité d'information"]
        for _, title, summary, feed in scored[: int(top_n)]:
            lines.append(f"- [{feed}] {title} :: {summary[:220]}")
        return "\n".join(lines)

    def http_get(url: str, max_chars: int = 2000) -> str:
        if not NETWORK_ENABLED:
            raise ToolError(
                "réseau désactivé dans cette démo (AGENTDEMO_ALLOW_NETWORK=0) — "
                "les scénarios hors-ligne utilisent les fichiers de fixtures"
            )
        if not url.startswith(("http://", "https://")):
            raise ToolError("seuls http(s) sont autorisés")
        request = urllib.request.Request(url, headers={"User-Agent": "agent-computer-demo/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                body = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ToolError(f"échec réseau : {exc}") from exc
        return _clip(body, int(max_chars))

    return {
        "fs_list": Tool("fs_list", "fs_list(path)", "liste un dossier du bac à sable", fs_list),
        "fs_read": Tool("fs_read", "fs_read(path, max_chars?)", "lit un fichier texte", fs_read),
        "fs_write": Tool("fs_write", "fs_write(path, content)", "écrit un fichier (livrable)", fs_write),
        "fs_move": Tool("fs_move", "fs_move(src, dst)", "déplace un fichier", fs_move),
        "csv_profile": Tool("csv_profile", "csv_profile(path)", "statistiques d'un CSV", csv_profile),
        "chart_bar": Tool(
            "chart_bar",
            "chart_bar(path, label_column, value_column, output, title?)",
            "génère un graphique SVG à partir d'un CSV",
            chart_bar,
        ),
        "rss_rank": Tool("rss_rank", "rss_rank(paths[], top_n?)", "lit des flux RSS et les classe", rss_rank),
        "http_get": Tool("http_get", "http_get(url, max_chars?)", "GET HTTP (désactivé par défaut)", http_get),
        "skill_list": Tool("skill_list", "skill_list()", "liste les procédures déjà apprises", skill_list),
        "skill_recall": Tool(
            "skill_recall",
            "skill_recall(keyword?)",
            "relit une procédure apprise avant d'agir (mémoire persistante)",
            skill_recall,
        ),
        "skill_write": Tool(
            "skill_write",
            "skill_write(name, content)",
            "enregistre une procédure réutilisable après un échec ou une découverte",
            skill_write,
        ),
    }


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _bar_svg(series: list[tuple[str, float]], title: str, unit: str) -> str:
    width, height = 640, 340
    left, top, bottom = 60, 50, 40
    plot_w, plot_h = width - left - 20, height - top - bottom
    peak = max(value for _, value in series) or 1.0
    slot = plot_w / len(series)
    bar_w = min(64, slot * 0.6)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#12151c"/>',
        f'<text x="{left}" y="28" fill="#e8ecf4" font-family="monospace" font-size="15">{_escape(title)}</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{width - 20}" y2="{top + plot_h}" stroke="#39404f"/>',
    ]
    for index, (label, value) in enumerate(series):
        bar_h = (value / peak) * plot_h
        x = left + index * slot + (slot - bar_w) / 2
        y = top + plot_h - bar_h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="#5b8cff" rx="3"/>')
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" fill="#9aa6bd" font-family="monospace" '
            f'font-size="11" text-anchor="middle">{value:.0f}</text>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{top + plot_h + 18:.1f}" fill="#7c8698" font-family="monospace" '
            f'font-size="10" text-anchor="middle">{_escape(label[:13])}</text>'
        )
    parts.append(
        f'<text x="{width - 20}" y="{height - 8}" fill="#5e6675" font-family="monospace" '
        f'font-size="10" text-anchor="end">{_escape(unit)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
