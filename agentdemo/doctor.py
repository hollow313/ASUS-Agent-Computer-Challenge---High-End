"""Diagnostic : vérifier qu'une installation peut réellement faire tourner la démo.

Un juré qui se bloque sur un prérequis manquant ne juge pas le projet, il juge l'installation. Ce
module fait les contrôles à sa place, dans l'ordre, et dit clairement ce qui est vert, ce qui est
absent et ce qui est optionnel.

    python3 -m agentdemo doctor
    python3 -m agentdemo doctor --base-url http://MON-IP:1234/v1
"""

from __future__ import annotations

import json
import platform
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .planners import normalize_base_url
from .scenarios_loader import list_scenarios

MIN_PYTHON = (3, 10)


@dataclass
class Check:
    name: str
    status: str  # "ok", "warn", "fail"
    detail: str = ""
    required: bool = True


def run_checks(data_dir: Path, base_url: str | None = None, model: str | None = None) -> list[Check]:
    checks: list[Check] = []

    version = sys.version_info
    ok_python = (version.major, version.minor) >= MIN_PYTHON
    states = sorted((data_dir / "runs").glob("*/state.json")) if (data_dir / "runs").is_dir() else []
    resumable = []
    for state in states:
        try:
            payload = json.loads(state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("status") != "done":
            resumable.append(state.parent.name)
    checks.append(
        Check(
            "Runs reprenables",
            "ok",
            f"{len(resumable)} état(s) disponible(s)" + (f" : {', '.join(resumable[:3])}" if resumable else ""),
            required=False,
        )
    )

    checks.append(
        Check(
            "Python 3.10 ou plus",
            "ok" if ok_python else "fail",
            f"{platform.python_version()} détecté",
        )
    )

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=data_dir, prefix=".doctor-", delete=True):
            pass
        checks.append(Check("Dossier de données inscriptible", "ok", str(data_dir)))
    except OSError as exc:
        checks.append(Check("Dossier de données inscriptible", "fail", f"{data_dir} : {exc}"))

    try:
        scenarios = list_scenarios()
        checks.append(
            Check(
                "Scénarios chargeables",
                "ok" if len(scenarios) >= 5 else "warn",
                ", ".join(s.slug for s in scenarios) or "aucun",
            )
        )
        empty = [s.slug for s in scenarios if not s.cassette()]
        checks.append(
            Check("Cassettes présentes", "ok" if not empty else "fail", ", ".join(empty) or "toutes")
        )
    except Exception as exc:  # noqa: BLE001 - un diagnostic ne doit jamais planter
        checks.append(Check("Scénarios chargeables", "fail", str(exc)))

    try:
        from .skills import SkillStore

        store = SkillStore(data_dir / "skills")
        checks.append(
            Check("Mémoire procédurale accessible", "ok", f"{len(store.list())} procédure(s)")
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("Mémoire procédurale accessible", "fail", str(exc)))

    try:
        usage = shutil.disk_usage(data_dir)
        free_gb = usage.free / 1e9
        checks.append(
            Check("Espace disque", "ok" if free_gb > 0.5 else "warn", f"{free_gb:.0f} Go libres")
        )
    except OSError as exc:
        checks.append(Check("Espace disque", "warn", str(exc)))

    docker = shutil.which("docker")
    checks.append(
        Check(
            "Docker présent",
            "ok" if docker else "warn",
            docker or "absent, la version python3 fonctionne sans conteneur",
            required=False,
        )
    )

    if base_url:
        url = normalize_base_url(base_url)
        try:
            request = urllib.request.Request(f"{url}/models")
            with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310
                payload = json.loads(response.read().decode())
            models = [m.get("id", "?") for m in payload.get("data", [])]
            detail = f"{url} : {', '.join(models[:4]) or 'aucun modèle chargé'}"
            if model and models and model not in models:
                detail += f" (le modèle demandé « {model} » n'est pas dans la liste)"
            checks.append(Check("Endpoint de modèle", "ok" if models else "warn", detail, required=False))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            checks.append(Check("Endpoint de modèle", "warn", f"{url} injoignable : {exc}", required=False))
    else:
        checks.append(
            Check(
                "Endpoint de modèle",
                "warn",
                "non testé (optionnel, --base-url pour vérifier un modèle local)",
                required=False,
            )
        )
    return checks


def render(checks: list[Check]) -> str:
    marks = {"ok": "[ok]  ", "warn": "[info]", "fail": "[ko]  "}
    lines = [f"{marks[c.status]} {c.name}" + (f" : {c.detail}" if c.detail else "") for c in checks]
    failures = [c for c in checks if c.status == "fail" and c.required]
    lines.append("")
    if failures:
        lines.append(f"{len(failures)} contrôle(s) bloquant(s). Corrige-les avant de lancer la démo.")
    else:
        optional = [c for c in checks if c.status == "warn"]
        lines.append("Installation prête.")
        if optional:
            lines.append(f"{len(optional)} point(s) d'information, aucun bloquant.")
    return "\n".join(lines)


def doctor(data_dir: Path, base_url: str | None = None, model: str | None = None) -> tuple[str, int]:
    checks = run_checks(data_dir, base_url, model)
    failed = any(c.status == "fail" and c.required for c in checks)
    return render(checks), (1 if failed else 0)
