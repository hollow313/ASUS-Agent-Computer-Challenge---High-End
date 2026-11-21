"""Exemple d'outil installable : les N premières lignes d'un CSV, triées sur une colonne.

Aucune dépendance, aucune écriture hors du fichier de sortie demandé. Sert de gabarit : un outil du
catalogue est un dossier avec un manifeste, cette fonction `main`, et son empreinte sha256.
"""

from __future__ import annotations

import csv
from pathlib import Path


def main(path: str = "", column: str = "", n: int = 5, output: str = "") -> str:
    source = Path(path)
    if not source.is_file():
        return f"csv introuvable : {path}"
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return "aucune ligne de données"
    if column and column in rows[0]:
        try:
            rows.sort(key=lambda row: float(str(row[column]).replace(",", ".")), reverse=True)
        except ValueError:
            rows.sort(key=lambda row: str(row[column]), reverse=True)
    keep = max(1, min(int(n), 50))
    lines = [",".join(rows[0].keys())] + [",".join(str(row.get(c, "")) for c in rows[0]) for row in rows[:keep]]
    body = "\n".join(lines)
    if output:
        Path(output).write_text(body + "\n", encoding="utf-8")
        return f"{keep} lignes écrites dans {output} sur la colonne {column or 'aucune'}"
    return body
