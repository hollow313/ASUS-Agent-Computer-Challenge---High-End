"""Export d'un run en archive lisible.

Un journal JSON sur un serveur, personne ne le lit. Une archive ZIP avec le journal, les livrables
et une page de synthèse, un juré la garde et la rouvre.

    python3 -m agentdemo export --run 4f1c2b8a          # dernière passe du run
    python3 -m agentdemo export --run 4f1c2b8a --out audit.zip
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExportedRun:
    run_id: str
    path: Path
    journal_files: list[str]
    artifact_files: list[str]

    def summary(self) -> str:
        return (
            f"{self.path} ({self.path.stat().st_size // 1024} Ko) · "
            f"{len(self.journal_files)} journal(aux) · {len(self.artifact_files)} livrable(s)"
        )


def _find_run(runs_dir: Path, run_id: str) -> tuple[list[Path], Path | None]:
    """Retrouve les journaux (une passe = un fichier) et l'espace de travail d'un run."""
    journals = sorted(runs_dir.glob(f"{run_id}*.json"))
    workspace = runs_dir / run_id / "workspace"
    return journals, workspace if workspace.is_dir() else None


def export_run(runs_dir: Path, run_id: str, out: Path | None = None) -> ExportedRun:
    journals, workspace = _find_run(Path(runs_dir), run_id)
    if not journals and workspace is None:
        raise FileNotFoundError(f"run introuvable : {run_id}")

    destination = Path(out) if out else Path(runs_dir) / f"{run_id}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    journal_names: list[str] = []
    artifact_names: list[str] = []
    declared: list[str] = []
    summary_lines = [f"Run {run_id}", ""]

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for journal in journals:
            archive.write(journal, f"journal/{journal.name}")
            journal_names.append(journal.name)
            data = json.loads(journal.read_text(encoding="utf-8"))
            for name in data.get("artifacts", []):
                if name not in declared:
                    declared.append(name)
            summary_lines += [
                f"passe {journal.stem.split('-p')[-1]}",
                f"  statut    : {data.get('status')}",
                f"  objectif  : {data.get('objective', '')[:120]}",
                f"  étapes    : {len(data.get('steps', []))}",
                f"  livrables : {', '.join(data.get('artifacts', [])) or 'aucun'}",
                f"  bilan     : {data.get('summary', '')[:200]}",
                "",
            ]
        if workspace:
            # on n'archive que ce que l'agent déclare comme livrable, pas les fixtures d'entrée
            candidates = (
                [workspace / name for name in declared]
                if declared
                else [f for f in sorted(workspace.rglob("*")) if f.is_file()]
            )
            for file in candidates:
                if file.is_file():
                    relative = file.relative_to(workspace).as_posix()
                    archive.write(file, f"livrables/{relative}")
                    artifact_names.append(relative)
        archive.writestr("LISEZ-MOI.txt", "\n".join(summary_lines))
    return ExportedRun(run_id, destination, journal_names, artifact_names)


def list_runs(runs_dir: Path) -> list[str]:
    """Identifiants de run, du plus récent au plus ancien."""
    ids = {path.name.split("-p")[0].replace(".json", "") for path in Path(runs_dir).glob("*.json")}
    paths = [(runs_dir / f"{run_id}.json", run_id) for run_id in ids]
    ordered = sorted(paths, key=lambda item: item[0].stat().st_mtime if item[0].exists() else 0, reverse=True)
    return [run_id for _, run_id in ordered]
