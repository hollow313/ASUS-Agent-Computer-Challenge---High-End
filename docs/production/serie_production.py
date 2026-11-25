"""Relit une archive de briefings de veille et publie la série de production.

Ce script ne lance rien : il **relit** les fichiers produits par une instance en
production (un briefing par jour ouvré, écrit par le planificateur) et rend les
chiffres publiés dans `docs/SERIE-PRODUCTION.md`.

    python3 docs/production/serie_production.py --archive /chemin/vers/archive
    python3 docs/production/serie_production.py --archive ... --markdown
    python3 docs/production/serie_production.py --archive ... --json

Ce qu'il mesure, fichier par fichier :

* la date du run, lue dans le nom du fichier (`2026-11-25_08-00-24.md`) ;
* le nombre d'items du briefing (lignes commençant par `• `) ;
* la taille du briefing seul, sans l'en-tête du planificateur ni le prompt ;
* la couverture : jours ouvrés de la période contre jours réellement produits.

Le format d'entrée est celui du planificateur Hermes : un bloc d'en-tête, le
prompt, la sortie du script de collecte, puis `## Response` qui contient le
briefing livré. Un fichier sans section `## Response` est ignoré et compté.

La durée n'est **pas** publiée : le planificateur n'écrit pas d'horodatage de fin,
et la date de modification du fichier ne mesure pas le run. Mieux vaut pas de
chiffre qu'un chiffre faux.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})\.md$")
RESPONSE = "\n## Response"
HOLIDAY = re.compile(r"jour f[ée]ri[ée]", re.I)


def briefing_of(path: Path) -> str:
    """Le briefing livré, sans l'en-tête du planificateur ni le prompt."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    index = text.find(RESPONSE)
    return text[index + len(RESPONSE):].strip() if index >= 0 else ""


def items_of(briefing: str) -> int:
    return len(re.findall(r"(?m)^• ", briefing))


def read_one(path: Path) -> dict | None:
    match = NAME.match(path.name)
    if not match:
        return None
    briefing = briefing_of(path)
    if not briefing:
        return None
    return {
        "date": match.group(1),
        "items": items_of(briefing),
        "chars": len(briefing),
        "holiday": bool(HOLIDAY.search(briefing[:200])),
    }


def weekday_count(first: str, last: str) -> int:
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    total, day = 0, start
    while day <= end:
        if day.weekday() < 5:
            total += 1
        day += timedelta(days=1)
    return total


def load(archive: Path) -> tuple[list[dict], int]:
    rows, skipped = [], 0
    for path in sorted(archive.glob("*.md")):
        row = read_one(path)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return rows, skipped


def summarise(rows: list[dict], skipped: int) -> dict:
    items = [row["items"] for row in rows]
    chars = [row["chars"] for row in rows]
    expected = weekday_count(rows[0]["date"], rows[-1]["date"]) if rows else 0
    return {
        "runs": len(rows),
        "first": rows[0]["date"] if rows else None,
        "last": rows[-1]["date"] if rows else None,
        "skipped": skipped,
        "weekdays": expected,
        "missing": max(0, expected - len(rows)),
        "holiday_runs": sum(1 for row in rows if row["holiday"]),
        "items_total": sum(items),
        "items_median": statistics.median(items) if items else 0,
        "chars_total": sum(chars),
        "chars_median": int(statistics.median(chars)) if chars else 0,
        "rows": rows,
    }


def markdown(data: dict) -> str:
    lines = [
        f"{data['runs']} runs, du {data['first']} au {data['last']}, "
        f"{data['items_total']} items, médiane {data['items_median']:.0f} items et "
        f"{data['chars_median']} caractères par briefing.",
        "",
        f"Jours ouvrés sur la période : {data['weekdays']} ; runs produits : {data['runs']} ; "
        f"manquants : {data['missing']}.",
        "",
        "| Date | Items | Caractères |",
        "| --- | --- | --- |",
    ]
    for row in data["rows"]:
        lines.append(f"| {row['date']} | {row['items']} | {row['chars']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="série de production d'une veille planifiée")
    parser.add_argument("--archive", required=True, help="dossier des fichiers de briefing")
    parser.add_argument("--json", action="store_true", help="sortie JSON complète")
    parser.add_argument("--markdown", action="store_true", help="tableau Markdown")
    parser.add_argument("--out", default="", help="fichier de sortie (défaut : stdout)")
    args = parser.parse_args()

    rows, skipped = load(Path(args.archive))
    if not rows:
        print("aucun fichier exploitable")
        return 1
    data = summarise(rows, skipped)

    if args.json:
        payload = json.dumps(data, ensure_ascii=False, indent=1)
    elif args.markdown:
        payload = markdown(data)
    else:
        payload = (
            f"runs            : {data['runs']}\n"
            f"période         : {data['first']} -> {data['last']}\n"
            f"jours ouvrés    : {data['weekdays']} (manquants : {data['missing']})\n"
            f"items           : {data['items_total']} ({data['items_median']:.0f} par run)\n"
            f"caractères      : {data['chars_total']} (médiane {data['chars_median']})\n"
            f"runs fériés     : {data['holiday_runs']}\n"
            f"ignorés         : {data['skipped']}\n"
        )

    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print("écrit", args.out)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
