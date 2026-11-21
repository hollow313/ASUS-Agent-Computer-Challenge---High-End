"""Exécution de commandes confinée.

Trois niveaux, du plus fort au plus faible, décidés au démarrage et **écrits dans le rapport du run** :

1. `bwrap` : bulle complète, système en lecture seule, `/tmp` et `$HOME` en mémoire, réseau coupé
   par `--unshare-all`, seul le dossier du run est inscriptible ;
2. `unshare -n` : réseau coupé par le noyau, reste du système visible ;
3. `aucune` : refusée par défaut. Autorisée seulement si l'opérateur pose
   `AGENTDEMO_ALLOW_UNSANDBOXED_EXEC=1`, et alors l'isolation annoncée est explicitement « aucune ».

Un agent qui exécute des commandes doit dire dans quel bac il les exécute. Le mode est donc une
donnée du run, jamais une variable d'environnement oubliée.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT = 6000
DEFAULT_TIMEOUT = 120
_PROBE: str | None = None


class SandboxError(RuntimeError):
    """Refus d'exécution, avec la raison lisible par l'agent."""


@dataclass
class ExecResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    isolation: str
    network: str

    def as_text(self) -> str:
        parts = [f"code retour : {self.returncode}"]
        if self.timed_out:
            parts.append("interrompu : délai dépassé")
        parts.append(f"isolation : {self.isolation}, réseau : {self.network}")
        if self.stdout.strip():
            parts.append(f"sortie :\n{self.stdout.strip()[:MAX_OUTPUT]}")
        if self.stderr.strip():
            parts.append(f"erreurs :\n{self.stderr.strip()[:MAX_OUTPUT]}")
        if not self.stdout.strip() and not self.stderr.strip():
            parts.append("aucune sortie")
        return "\n".join(parts)


def isolation_level() -> str:
    """Quel bac à sable est réellement disponible sur cette machine."""
    global _PROBE
    if _PROBE is not None:
        return _PROBE
    if shutil.which("bwrap"):
        probe = subprocess.run(
            ["bwrap", "--ro-bind", "/", "/", "--unshare-all", "true"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if probe.returncode == 0:
            _PROBE = "bwrap"
            return _PROBE
    if shutil.which("unshare"):
        probe = subprocess.run(
            ["unshare", "-n", "true"], capture_output=True, text=True, timeout=20
        )
        if probe.returncode == 0:
            _PROBE = "unshare"
            return _PROBE
    _PROBE = "aucune"
    return _PROBE


def runner_for(workspace: Path, scenario: object) -> "CommandSandbox | None":
    """Un exécuteur seulement si l'exécution est possible : isolée, ou explicitement autorisée.

    Sinon l'outil `run` n'est pas exposé du tout, ce qui évite qu'un modèle le découvre, l'appelle,
    se fasse refuser et consomme son budget pour rien.
    """
    policy = {}
    if hasattr(scenario, "exec_policy"):
        try:
            policy = scenario.exec_policy() or {}
        except (TypeError, ValueError):
            policy = {}
    if isolation_level() == "aucune" and not policy.get("allow_unsandboxed"):
        return None
    network = "deny"
    if hasattr(scenario, "network") and isinstance(getattr(scenario, "network"), dict):
        network = str(scenario.network.get("mode", "deny"))
    return CommandSandbox(workspace, network=network, allow_unsandboxed=bool(policy.get("allow_unsandboxed")))


class CommandSandbox:
    """Lance une commande shell dans le dossier du run, avec la politique réseau du scénario."""

    def __init__(
        self,
        workspace: Path,
        network: str = "deny",
        timeout: int = DEFAULT_TIMEOUT,
        allow_unsandboxed: bool = False,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.network = network if network in ("deny", "allowlist", "open") else "deny"
        self.timeout = timeout
        self.allow_unsandboxed = allow_unsandboxed

    def _bwrap(self, command: str) -> list[str]:
        argv = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--tmpfs", "/home",
            "--bind", str(self.workspace), str(self.workspace),
            "--chdir", str(self.workspace),
            "--unshare-all",
        ]
        if self.network != "deny":
            # la politique est alors appliquée par l'outil réseau, et le dit dans le rapport
            argv.append("--share-net")
        argv += [
            "--die-with-parent",
            "--clearenv",
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
            "--setenv", "HOME", "/tmp",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--setenv", "LANG", "C.UTF-8",
            "/bin/sh", "-c", command,
        ]
        return argv

    def run(self, command: str) -> ExecResult:
        command = str(command or "").strip()
        if not command:
            raise SandboxError("commande vide")
        level = isolation_level()
        allowed_here = self.allow_unsandboxed or os.environ.get("AGENTDEMO_ALLOW_UNSANDBOXED_EXEC") == "1"
        if level == "aucune" and not allowed_here:
            raise SandboxError(
                "aucun bac à sable disponible (bwrap ou unshare) : exécution refusée. "
                "Pose AGENTDEMO_ALLOW_UNSANDBOXED_EXEC=1 pour l'autoriser, en connaissance de cause."
            )
        if level == "bwrap":
            argv = self._bwrap(command)
        elif level == "unshare":
            argv = ["unshare", "-n", "--", "/bin/sh", "-c", command]
        else:
            argv = ["/bin/sh", "-c", command]

        started = time.perf_counter()
        timed_out = False
        try:
            completed = subprocess.run(
                argv,
                cwd=None if level != "aucune" else str(self.workspace),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=(
                    {
                        "PATH": "/usr/local/bin:/usr/bin:/bin",
                        "HOME": str(self.workspace),
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "LANG": "C.UTF-8",
                    }
                    if level == "aucune"
                    else None
                ),
            )
            code, out, err = completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            code = 124
            out = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            err = f"délai de {self.timeout} s dépassé"
        duration = int((time.perf_counter() - started) * 1000)
        network = self.network
        if level == "bwrap" and self.network == "deny":
            network = "deny (noyau)"
        elif level == "unshare":
            network = "deny (noyau)"
        if level == "aucune":
            level = "aucune (déclarée par le scénario)" if self.allow_unsandboxed else "aucune"
            network = f"{self.network} (non isolé)"
        return ExecResult(command, code, out, err, duration, timed_out, level, network)
