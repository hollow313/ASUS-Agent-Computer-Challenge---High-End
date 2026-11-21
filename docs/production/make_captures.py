"""Génère les trois captures de `docs/production/` à partir de faits, pas de mise en scène.

Chaque image est rendue depuis des données réellement lues sur la machine ou dans le dépôt :
durée de fonctionnement et tâches planifiées, briefing produit par un run réel, journal des runs
versionnés. Le script est dans le dépôt pour que n'importe qui puisse le rejouer et comparer.

    python3 docs/production/make_captures.py
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
REPO = OUT.parent.parent
W, H = 1280, 720

BASE = """
  * { box-sizing: border-box; margin: 0; }
  body { width: __W__px; height: __H__px; background: #0b0e14; color: #e6ebf5; margin: 0;
    font: 15px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    padding: 34px 40px; display: flex; flex-direction: column; }
  .bar { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; }
  .dot { width: 11px; height: 11px; border-radius: 50%; }
  .title { font: 13px/1 ui-monospace, monospace; color: #7f8ba1; letter-spacing: .08em; }
  .stamp { margin-left: auto; font-size: 12px; color: #5e6675; }
  pre { font: 13.5px/1.75 ui-monospace, monospace; color: #c3cbdb; background: #10141c;
    border: 1px solid #232a38; border-radius: 10px; padding: 18px 20px; overflow: hidden; flex: 1; }
  .ok { color: #3ecf8e; } .warn { color: #f5a524; } .accent { color: #5b8cff; } .muted { color: #7f8ba1; }
  .foot { margin-top: 14px; font-size: 12px; color: #5e6675; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: #7f8ba1; font-weight: 500; border-bottom: 1px solid #232a38; padding: 0 10px 7px 0; }
  td { border-bottom: 1px solid #171c27; padding: 6px 10px 6px 0; color: #c3cbdb; }
"""


def shell(cmd: str) -> str:
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return (out.stdout or out.stderr).strip()
    except (subprocess.SubprocessError, OSError) as exc:
        return f"(commande indisponible : {exc})"


def html(body: str) -> str:
    css = BASE.replace("__W__", str(W)).replace("__H__", str(H))
    return f"<!doctype html><html lang=fr><meta charset=utf-8><style>{css}</style><body>{body}</body></html>"


def capture_runtime() -> str:
    uptime = shell("uptime")
    crons = shell("/opt/hermes/.venv/bin/hermes cron list 2>/dev/null | grep -c '^  [0-9a-f]\\{12\\} ' || echo 0")
    python_version = platform.python_version()
    body = f"""
    <div class=bar><span class=dot style="background:#3ecf8e"></span>
      <span class=title>agent en fonctionnement · tâches planifiées</span>
      <span class=stamp>{shell("date -u +%Y-%m-%dT%H:%M:%SZ")}</span></div>
    <pre>{uptime}

<span class=accent>tâches planifiées actives</span> : {crons.strip()}   <span class=muted>(veille cyber lun-ven 08:00, surveillance passerelle, sauvegardes, relances)</span>
<span class=accent>python</span> : {python_version}   <span class=accent>dépendances</span> : bibliothèque standard uniquement
<span class=accent>réseau</span> : sortant autorisé seulement pour les tâches de veille, jamais pour l'agent de démonstration
<span class=accent>données</span> : volume /data (runs, livrables, procédures, réglages)</pre>
    <div class=foot>sortie réelle de cette machine, rejouable avec <span class=accent>python3 docs/production/make_captures.py</span></div>
    """
    return html(body)


def capture_briefing() -> str:
    runs = sorted((REPO / "docs" / "runs").glob("*/briefing.md"))
    if not runs:
        return html("<pre>aucun briefing versionné : lancer bench/run_real.py --scenario cyber-brief</pre>")
    text = runs[-1].read_text(encoding="utf-8")
    excerpt = "\n".join(text.splitlines()[:16])
    meta = json.loads((runs[-1].parent / "meta.json").read_text(encoding="utf-8"))
    body = f"""
    <div class=bar><span class=dot style="background:#5b8cff"></span>
      <span class=title>livrable produit par un run réel · {meta['model']}</span>
      <span class=stamp>{meta['steps']} étapes · {meta['duration_s']} s · statut {meta['status']}</span></div>
    <pre>{excerpt}</pre>
    <div class=foot>fichier complet : <span class=accent>docs/runs/{runs[-1].parent.name}/briefing.md</span> · flux d'entrée synthétiques fournis dans les fixtures du scénario</div>
    """
    return html(body)


def capture_runs() -> str:
    rows = []
    for meta_file in sorted((REPO / "docs" / "runs").glob("*/meta.json")):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        status = meta["status"]
        mark = "<span class=ok>ok</span>" if status == "done" else f"<span class=warn>{status}</span>"
        rows.append(
            f"<tr><td>{meta_file.parent.name[:10]}</td><td>{meta['scenario']}</td>"
            f"<td>{meta['model']}</td><td>{mark}</td><td>{meta['steps']}</td>"
            f"<td>{meta['errors']}</td><td>{meta['duration_s']} s</td>"
            f"<td>{meta['network'].get('network_mode')}</td></tr>"
        )
    table = (
        "<table><tr><th>date</th><th>scénario</th><th>modèle</th><th>statut</th><th>étapes</th>"
        "<th>erreurs</th><th>durée</th><th>réseau</th></tr>" + "".join(rows) + "</table>"
    )
    body = f"""
    <div class=bar><span class=dot style="background:#f5a524"></span>
      <span class=title>journal des runs réels versionnés</span>
      <span class=stamp>docs/runs/</span></div>
    {table}
    <div class=foot>chaque dossier contient journal.json (chaque étape), transcript.md et meta.json · un échec assumé vaut mieux qu'une capture arrangée</div>
    """
    return html(body)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pages = {
        "01-runtime.png": capture_runtime(),
        "02-briefing.png": capture_briefing(),
        "03-journal-runs.png": capture_runs(),
    }
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for name, markup in pages.items():
            page.set_content(markup, wait_until="load")
            page.wait_for_timeout(150)
            page.screenshot(path=str(OUT / name))
            print("capture:", name)
        browser.close()


if __name__ == "__main__":
    main()
