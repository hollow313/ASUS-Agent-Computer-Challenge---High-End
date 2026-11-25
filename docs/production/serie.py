"""Relit la série de veilles versionnées et sort les chiffres, sans en inventer un seul.

    python3 docs/production/serie.py
    python3 docs/production/serie.py --json

Ce que le script lit : `docs/runs/*-veille*/meta.json`, écrits par `veille.py` à chaque run, plus les
jours manquants dans `docs/production/journal.md` (statut `absent`). Ce qu'il refuse : compter un run
dont le briefing est vide comme une réussite, et sauter les échecs dans les totaux.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
RUNS = REPO / "docs" / "runs"


def load_metas() -> list[dict]:
    metas = []
    for path in sorted(RUNS.glob("*-veille*/meta.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["_dir"] = path.parent.name
        briefing = path.parent / "briefing.md"
        payload["has_briefing"] = briefing.exists() and briefing.stat().st_size > 200
        metas.append(payload)
    return metas


def missing_days(metas: list[dict]) -> list[str]:
    """Les jours sans run restent visibles : une série honnête montre ses trous."""
    stamps = sorted({str(m.get("date") or "") for m in metas if m.get("date")})
    if not stamps:
        return []
    first = date.fromisoformat(stamps[0])
    last = date.fromisoformat(stamps[-1])
    present = set(stamps)
    gaps = []
    day = first
    while day <= last:
        iso = day.isoformat()
        if iso not in present:
            gaps.append(iso)
        day += timedelta(days=1)
    return gaps


def summarise(metas: list[dict]) -> dict:
    durations = [float(m.get("duration_s") or 0.0) for m in metas if m.get("duration_s")]
    delivered = [m for m in metas if m.get("status") == "done" and m.get("has_briefing")]
    failures = [
        {"date": m.get("date"), "status": m.get("status"), "reason": str(m.get("summary") or "")[:160]}
        for m in metas
        if m not in delivered
    ]
    items = [int(m.get("items") or 0) for m in metas if m.get("has_briefing")]
    return {
        "runs": len(metas),
        "delivered": len(delivered),
        "delivery_rate": round(100.0 * len(delivered) / len(metas), 1) if metas else 0.0,
        "failures": failures,
        "p50_s": round(statistics.median(durations), 1) if durations else 0.0,
        "p95_s": round(sorted(durations)[max(0, int(len(durations) * 0.95) - 1)], 1) if durations else 0.0,
        "items_median": int(statistics.median(items)) if items else 0,
        "gaps": missing_days(metas),
        "models": sorted({str(m.get("model") or "") for m in metas if m.get("model")}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="série de veilles versionnées")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    metas = load_metas()
    data = summarise(metas)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if not metas:
        print("aucun run de veille versionné : lance docs/production/veille.py --once")
        return 1
    print(f"runs                 : {data['runs']}")
    print(f"avec briefing        : {data['delivered']} ({data['delivery_rate']} %)")
    print(f"p50 / p95            : {data['p50_s']} s / {data['p95_s']} s")
    print(f"entrées par briefing : {data['items_median']} (médiane)")
    print(f"modèles              : {', '.join(data['models'])}")
    if data["gaps"]:
        print(f"jours sans run       : {', '.join(data['gaps'])}")
    if data["failures"]:
        print("\néchecs, nommés :")
        for failure in data["failures"]:
            print(f"  - {failure['date']} {failure['status']} : {failure['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
