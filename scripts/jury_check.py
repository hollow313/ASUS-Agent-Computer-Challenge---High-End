"""La commande unique du jury : tout ce qui est vérifiable hors ligne, en une page.

    make jury-check          # ou python3 scripts/jury_check.py

Ce que le script lance, dans l'ordre : la suite de tests, les scénarios en replay, la validation des
cassettes contre les outils réels, le diagnostic d'installation, et le dimensionnement mémoire pour
32 Go. Il écrit `docs/JURY-CHECK.md` — sans horodatage, sans nombre aléatoire : relancé sur le même commit,
le fichier est identique au caractère près, et `git diff` reste vide.

Sortie 0 si tout passe, 1 sinon. La dernière ligne est la seule que le jury doit retenir.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "JURY-CHECK.md"
PYTHON = sys.executable


def run(args: list[str], timeout: int = 600) -> tuple[int, str]:
    proc = subprocess.run(
        [PYTHON, *args], cwd=REPO, capture_output=True, text=True, timeout=timeout, check=False
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def scenarios() -> list[str]:
    """La liste vient du chargeur, pas d'une sortie de console qu'on analyserait à la main."""
    sys.path.insert(0, str(REPO))
    try:
        from agentdemo.scenarios_loader import list_scenarios

        return [(scenario.slug, scenario.has_cassette()) for scenario in list_scenarios()]
    except Exception:  # noqa: BLE001 - un import cassé doit se voir dans le rapport, pas planter
        return []


def main() -> int:
    rows: list[tuple[str, str, str]] = []

    code, out = run(["-m", "unittest", "discover", "-s", "tests"])
    tests = re.search(r"Ran (\d+) tests", out)
    tests_count = int(tests.group(1)) if tests else 0
    rows.append(("tests unitaires", "ok" if code == 0 else "échec", f"{tests_count} tests"))

    scen = scenarios()
    replayable = [slug for slug, has_cassette in scen if has_cassette]
    live_only = [slug for slug, has_cassette in scen if not has_cassette]
    done, failed = 0, []
    for slug in replayable:
        code, out = run(["-m", "agentdemo", "run", "--scenario", slug], timeout=300)
        if code == 0 and "statut    : done" in out:
            done += 1
        else:
            failed.append(slug)
    detail = f"{done}/{len(replayable)} terminés"
    if live_only:
        detail += f" · live uniquement : {', '.join(live_only)}"
    rows.append(
        ("scénarios en replay", "ok" if replayable and done == len(replayable) else "échec", detail)
    )

    code, out = run(["-m", "agentdemo", "validate"])
    rows.append(("cassettes contre outils réels", "ok" if code == 0 else "échec", out.strip().splitlines()[-1] if out.strip() else ""))

    code, out = run(["-m", "agentdemo", "doctor"])
    rows.append(("diagnostic d'installation", "ok" if code == 0 else "échec", "prêt" if code == 0 else "bloquant"))

    code, out = run(["-m", "agentdemo", "fit", "--vram", "32", "--context", "32768"])
    fit_line = ""
    for line in out.splitlines():
        if "qwen2.5-coder-32b" in line:
            fit_line = " ".join(line.split())
    rows.append(("dimensionnement 32 Go", "ok" if code == 0 else "échec", fit_line or "sortie inattendue"))

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        commit = "inconnu"

    ok = all(status == "ok" for _, status, _ in rows)
    lines = [
        "# Vérification du jury",
        "",
        "Cette page est produite par `make jury-check`, pas écrite à la main. Relancée sur le même commit,",
        "elle sort identique : c'est le point de départ d'une preuve, pas une capture d'écran.",
        "",
        "| contrôle | résultat | détail |",
        "| --- | --- | --- |",
    ]
    for name, status, detail in rows:
        lines.append(f"| {name} | {status} | {detail} |")
    lines += [
        "",
        f"Commit : `{commit}`",
        "",
        "## Ce que cette page ne dit pas",
        "",
        "Elle vérifie la mécanique, pas la qualité d'un modèle. Les chiffres de réussite sont dans",
        "`docs/mesures/`, datés, avec la commande qui les produit. Le détail des scénarios est dans",
        "`docs/SCENARIOS.md`, les runs réels dans `docs/runs/`.",
        "",
    ]
    if failed:
        lines += ["Scénarios en échec : " + ", ".join(failed), ""]
    final = (
        f"jury-check : {'OK' if ok else 'ÉCHEC'} — {tests_count} tests, {done}/{len(replayable)} scénarios, "
        f"{'cassettes vertes' if rows[2][1] == 'ok' else 'cassettes en échec'}, fit 32 Go"
    )
    lines.append(final)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(final)
    print(f"page : {OUT.relative_to(REPO)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
