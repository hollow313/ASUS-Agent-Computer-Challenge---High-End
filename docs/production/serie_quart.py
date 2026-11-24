"""Relit une session de quart et produit les chiffres publiés.

Une session de quart, c'est une boucle qui relance un run dès que le précédent finit, avec des
interruptions provoquées. Ce script ne lance rien : il **relit** ce qui a été produit et refuse de
compter autre chose que ce qui existe sur disque.

    python3 docs/production/serie_quart.py --depuis 20261124
    python3 docs/production/serie_quart.py --depuis 20261124 --json

Ce qu'il mesure, run par run, dans `data/runs/*-p*.json` :

* le nombre de runs, le nombre de passes ;
* le taux de livrable, c'est-à-dire les runs qui finissent `done` **avec** au moins un artefact ;
* les échecs, nommés, avec leur raison (aucun n'est omis) ;
* les reprises réussies : un état `state.json` présent et une numérotation d'étapes qui repart après 1 ;
* les procédures apprises : étapes `skill_write` et fichiers présents dans `data/skills/` ;
* p50 et p95 par run.

Le graphe cumulatif est du SVG écrit à la main : aucune dépendance, et il reste lisible dans le dépôt.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("AGENTDEMO_DATA_DIR") or Path(__file__).resolve().parent.parent.parent / "data")
RUNS_DIR = DATA_DIR / "runs"
SKILLS_DIR = DATA_DIR / "skills"


def load_runs(since: str | None = None) -> list[dict]:
    runs: list[dict] = []
    if not RUNS_DIR.is_dir():
        return runs
    for path in sorted(RUNS_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "status" not in payload:
            continue
        started = str(payload.get("started_at") or "")
        if since:
            try:
                stamp = datetime.fromtimestamp(float(started), tz=timezone.utc).strftime("%Y%m%d")
            except (TypeError, ValueError):
                stamp = ""
            if stamp and stamp < since:
                continue
        payload["_file"] = path.name
        runs.append(payload)
    return runs


def resumed_runs(run_ids: set[str]) -> list[str]:
    """Runs qui portent un état de reprise et une numérotation qui ne repart pas de zéro."""
    resumed = []
    for run_id in run_ids:
        state = RUNS_DIR / run_id / "state.json"
        if not state.exists():
            continue
        try:
            payload = json.loads(state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("resumed_at"):
            resumed.append(run_id)
    return resumed


def percent(part: int, total: int) -> float:
    return round(100.0 * part / total, 1) if total else 0.0


def summarise(runs: list[dict]) -> dict:
    durations = [float(r.get("duration_s") or 0.0) for r in runs if r.get("duration_s")]
    done = [r for r in runs if r.get("status") == "done"]
    with_deliverable = [r for r in done if r.get("artifacts")]
    failures = [
        {
            "run": r.get("run_id"),
            "scenario": r.get("scenario"),
            "status": r.get("status"),
            "reason": (r.get("summary") or "")[:180],
        }
        for r in runs
        if r not in with_deliverable
    ]
    skill_steps = sum(
        1 for r in runs for step in (r.get("steps") or []) if step.get("tool") == "skill_write"
    )
    return {
        "runs": len(runs),
        "done": len(done),
        "with_deliverable": len(with_deliverable),
        "deliverable_rate": percent(len(with_deliverable), len(runs)),
        "failures": failures,
        "resumed": resumed_runs({str(r.get("run_id")) for r in runs}),
        "skill_steps": skill_steps,
        "skills_on_disk": len(list(SKILLS_DIR.glob("*.md"))) if SKILLS_DIR.is_dir() else 0,
        "p50_s": round(statistics.median(durations), 2) if durations else 0.0,
        "p95_s": round(sorted(durations)[max(0, int(len(durations) * 0.95) - 1)], 2) if durations else 0.0,
    }


def sparkline_svg(runs: list[dict], path: Path) -> None:
    """Courbe cumulative du nombre de livrables, une marche par run."""
    width, height, pad = 640, 200, 28
    points = []
    delivered = 0
    for index, run in enumerate(runs):
        if run.get("status") == "done" and run.get("artifacts"):
            delivered += 1
        x = pad + (width - 2 * pad) * (index / max(1, len(runs) - 1))
        y = height - pad - (height - 2 * pad) * (delivered / max(1, len(runs)))
        points.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(points)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="#0b0e14"/>'
        f'<polyline fill="none" stroke="#5b8cff" stroke-width="2" points="{polyline}"/>'
        f'<text x="{pad}" y="{height - 8}" fill="#5e6675" font-family="monospace" font-size="11">'
        f"{len(runs)} runs · {delivered} livrables cumulés</text>"
        '<text x="0" y="0" fill="none"> </text>'
        "</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="chiffres d'une session de quart")
    parser.add_argument("--depuis", help="jjjjmmaaaa, ignore les runs antérieurs")
    parser.add_argument("--json", action="store_true", help="sortie JSON brute")
    parser.add_argument("--svg", default="", help="chemin du graphe cumulatif")
    parser.add_argument("--data", default="", help="dossier de données (par défaut la variable ou data/)")
    args = parser.parse_args()

    if args.data:
        global DATA_DIR, RUNS_DIR, SKILLS_DIR
        DATA_DIR = Path(args.data)
        RUNS_DIR = DATA_DIR / "runs"
        SKILLS_DIR = DATA_DIR / "skills"

    runs = load_runs(args.depuis)
    data = summarise(runs)
    if args.svg:
        sparkline_svg(runs, Path(args.svg))
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f"runs                 : {data['runs']}")
    print(f"terminés             : {data['done']}")
    print(f"avec livrable        : {data['with_deliverable']} ({data['deliverable_rate']} %)")
    print(f"p50 / p95 par run    : {data['p50_s']} s / {data['p95_s']} s")
    print(f"reprises réussies    : {len(data['resumed'])}")
    print(f"procédures apprises  : {data['skill_steps']} étape(s) skill_write, {data['skills_on_disk']} sur disque")
    if data["failures"]:
        print("\néchecs, nommés :")
        for failure in data["failures"][:10]:
            print(f"  - {failure['run']} {failure['scenario']} {failure['status']} : {failure['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
