"""Un déclencheur, pas seulement une horloge.

Un dossier surveillé : un fichier déposé devient un run, sans cron et sans opérateur. Trois garde-fous,
parce qu'un watcher naïf se déclenche sur sa propre sortie et corrompt un état :

* **verrou** : un fichier `.vigie.lock` dans le dossier de données. Si un run tourne, l'événement attend ;
  il n'est pas perdu, et deux runs ne se marchent pas dessus ;
* **exclusions** : `data/`, `runs/`, tout ce qui commence par un point, et le dossier de sortie ;
* **fichier stable** : deux relevés de taille espacés d'une seconde. Un `cp` de 40 Mo se voit avant
  d'être fini, et l'agent lirait un fichier tronqué.

    python3 -m agentdemo watch ./inbox --scenario inbox-triage --once
    python3 -m agentdemo watch ./inbox --scenario inbox-triage --interval 5
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

LOCK_NAME = ".vigie.lock"
IGNORED = {"data", "runs", "node_modules", "__pycache__"}


def lock_path(data_dir: Path) -> Path:
    return Path(data_dir) / LOCK_NAME


def acquire(data_dir: Path, stale_after: float = 6 * 3600) -> bool:
    """Pose le verrou. Un verrou plus vieux que `stale_after` est repris : un run tué ne bloque pas tout."""
    path = lock_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            age = 0.0
        if age < stale_after:
            return False
        path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    return True


def release(data_dir: Path) -> None:
    lock_path(data_dir).unlink(missing_ok=True)


def should_handle(path: Path, data_dir: Path, seen: set[str], root: Path | None = None) -> bool:
    """Un fichier mérite un run s'il est nouveau, stable et hors des dossiers de travail.

    Les exclusions se jugent **relativement au dossier surveillé** : un chemin absolu comme
    `/opt/data/...` contient « data » sans être le dossier de sortie de l'agent.
    """
    try:
        resolved = path.resolve()
    except OSError:
        return False
    data_root = Path(data_dir).resolve()
    if data_root in resolved.parents or resolved == data_root:
        return False  # ne jamais surveiller son propre dossier de sortie
    if root is not None:
        try:
            relative = resolved.relative_to(Path(root).resolve())
        except ValueError:
            return False
        if any(part in IGNORED for part in relative.parts[:-1]):
            return False
    elif any(part in IGNORED for part in resolved.parts[-3:-1]):
        return False
    if resolved.name.startswith(".") or resolved.name.endswith(".lock"):
        return False
    try:
        if not resolved.is_file() or resolved.stat().st_size == 0:
            return False
    except OSError:
        return False
    key = f"{resolved}:{resolved.stat().st_mtime_ns}"
    if key in seen:
        return False
    return True


def stable(path: Path, delay: float = 1.0) -> bool:
    """Deux relevés espacés : un fichier encore en cours d'écriture n'est pas traité."""
    try:
        first = path.stat().st_size
    except OSError:
        return False
    time.sleep(delay)
    try:
        return path.stat().st_size == first
    except OSError:
        return False


def snapshot(folder: Path, data_dir: Path) -> list[Path]:
    return sorted(p for p in Path(folder).rglob("*") if should_handle(p, data_dir, set()))


def deliver(path: Path, inputs_dir: Path) -> Path:
    """Le fichier est copié dans les entrées du run : l'original n'est jamais modifié."""
    inputs_dir.mkdir(parents=True, exist_ok=True)
    target = inputs_dir / path.name
    shutil.copy2(path, target)
    return target
