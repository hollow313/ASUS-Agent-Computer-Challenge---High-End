"""Catalogue d'outils déclaratifs : installer un outil sans installer de paquets.

La règle est simple et non négociable : **aucun `pip install`, aucun registre distant, aucun code
exécuté hors du dossier de données**. Un outil est un dossier avec un manifeste, un point d'entrée
Python et son empreinte sha256. On vérifie l'empreinte, on copie dans `data/tools/<nom>/`, on
recharge le registre. Une empreinte qui ne correspond pas est un refus, pas un avertissement.

Les refus sont journalisés dans `data/tools/install.jsonl` : qui a demandé quoi, ce qui a été refusé
et pourquoi. Un agent qui peut étendre son outillage doit garder la trace de ses extensions.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import time
from pathlib import Path
from typing import Any

from .tools import Tool, ToolError

CATALOG_DIR = Path(__file__).resolve().parent / "available_tools"


class CatalogError(RuntimeError):
    """Installation refusée, avec la raison lisible."""


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _journal(data_dir: Path, entry: dict[str, Any]) -> None:
    path = Path(data_dir) / "tools" / "install.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **entry}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def installed_dir(data_dir: Path, name: str) -> Path:
    root = (Path(data_dir) / "tools").resolve()
    target = (root / name).resolve()
    if root not in target.parents:
        raise CatalogError(f"nom d'outil refusé : {name}")
    return target


def installed(data_dir: Path) -> list[dict[str, Any]]:
    root = Path(data_dir) / "tools"
    rows = []
    for manifest in sorted(root.glob("*/manifest.json")):
        try:
            rows.append(json.loads(manifest.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def _validate(manifest: dict[str, Any]) -> None:
    for key in ("name", "version", "description", "entrypoint", "sha256"):
        if not manifest.get(key):
            raise CatalogError(f"manifeste incomplet : {key} manquant")
    name = str(manifest["name"])
    if not name.replace("-", "").replace("_", "").isalnum():
        raise CatalogError(f"nom d'outil invalide : {name!r}")
    entry = str(manifest["entrypoint"])
    if entry.startswith(("/", "..")) or ".." in Path(entry).parts:
        raise CatalogError(f"point d'entrée hors du dossier de l'outil : {entry!r}")
    if not entry.endswith(".py"):
        raise CatalogError("le point d'entrée doit être un fichier Python")


def load_tool(data_dir: Path, manifest: dict[str, Any]) -> Tool:
    """Charge un outil installé sous forme d'outil du registre (fonction `main(**args)`)."""
    directory = installed_dir(data_dir, str(manifest["name"]))
    path = directory / str(manifest["entrypoint"])
    if not path.is_file():
        raise CatalogError(f"point d'entrée absent : {path}")
    if _hash(path) != str(manifest["sha256"]):
        raise CatalogError(f"empreinte invalide pour {manifest['name']} : outil modifié après installation")
    spec = importlib.util.spec_from_file_location(f"vigie_tool_{manifest['name']}", path)
    if spec is None or spec.loader is None:
        raise CatalogError("module illisible")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # noqa: S102 - code local, empreinte vérifiée juste avant
    if not hasattr(module, "main"):
        raise CatalogError("le module doit exposer une fonction main")
    params = ", ".join(manifest.get("params", {}).keys())
    signature = f"{manifest['name']}({params})"
    return Tool(str(manifest["name"]), signature, str(manifest["description"]), module.main)


def install(
    data_dir: Path,
    source: str,
    *,
    force: bool = False,
    approved: bool = False,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    """Installe un outil depuis le catalogue embarqué (nom) ou depuis un dossier de manifeste."""
    catalog_dir = Path(catalog_dir or CATALOG_DIR)
    candidate = Path(source)
    if candidate.is_dir():
        source_dir = candidate
    else:
        source_dir = catalog_dir / str(source)
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.is_file():
        raise CatalogError(f"catalogue introuvable pour {source!r}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate(manifest)
    entry = source_dir / str(manifest["entrypoint"])
    if not entry.is_file():
        raise CatalogError(f"fichier absent dans le catalogue : {manifest['entrypoint']}")
    digest = _hash(entry)
    if digest != manifest["sha256"]:
        _journal(data_dir, {"event": "tool_install_refused", "name": manifest["name"], "reason": "sha256"})
        raise CatalogError(
            f"empreinte sha256 invalide pour {manifest['name']} : attendu {manifest['sha256'][:12]}…, "
            f"obtenu {digest[:12]}…"
        )
    if not approved:
        _journal(data_dir, {"event": "tool_install_refused", "name": manifest["name"], "reason": "sans accord"})
        raise CatalogError(
            "installation refusée : l'accord de l'opérateur est obligatoire (--yes), "
            f"empreinte {digest[:16]}…"
        )

    target = installed_dir(data_dir, str(manifest["name"]))
    if target.exists():
        if not force:
            raise CatalogError(f"outil déjà installé : {manifest['name']} (utilise --force)")
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target)
    _journal(
        data_dir,
        {"event": "tool_installed", "name": manifest["name"], "version": manifest["version"], "sha256": digest},
    )
    return {"name": manifest["name"], "version": manifest["version"], "sha256": digest, "path": str(target)}


def remove(data_dir: Path, name: str, *, approved: bool = False) -> dict[str, Any]:
    target = installed_dir(data_dir, name)
    if not target.exists():
        raise CatalogError(f"outil inconnu : {name}")
    if not approved:
        raise CatalogError("suppression refusée : --yes est obligatoire")
    shutil.rmtree(target)
    _journal(data_dir, {"event": "tool_removed", "name": name})
    return {"removed": name}
