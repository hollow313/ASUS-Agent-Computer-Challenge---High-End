"""Génère les cartons de la vidéo de candidature (titre, chiffres, fin)."""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("/data/agent-computer-challenge/video/slides")
OUT.mkdir(parents=True, exist_ok=True)
BENCH = Path("/data/agent-computer-challenge/bench")
W, H = 1280, 720

BASE_CSS = """
  * { box-sizing: border-box; margin: 0; }
  body {
    width: %dpx; height: %dpx; background: #0b0e14; color: #e6ebf5; margin: 0;
    font: 20px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 64px 72px; display: flex; flex-direction: column; justify-content: center;
  }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  .muted { color: #8a94a8; }
  .accent { color: #5b8cff; }
  .ok { color: #3ecf8e; }
""" % (W, H)

TITLE = f"""<!doctype html><html lang=fr><meta charset=utf-8><style>{BASE_CSS}
  .kicker {{ font: 15px/1 var(--m); letter-spacing: .22em; text-transform: uppercase; color: #5b8cff; margin-bottom: 26px; font-family: ui-monospace, monospace; }}
  h1 {{ font-size: 54px; line-height: 1.15; letter-spacing: -.015em; margin-bottom: 22px; font-weight: 680; }}
  h1 span {{ color: #5b8cff; }}
  p {{ color: #9aa4b8; font-size: 21px; max-width: 900px; }}
  .rule {{ width: 72px; height: 3px; background: #5b8cff; margin: 30px 0; }}
  .foot {{ margin-top: 44px; font: 14px/1.6 ui-monospace, monospace; color: #5e6675; }}
</style>
<body>
  <div class=kicker>ASUS Agent Computer Challenge · High-End</div>
  <h1>Un agent qui <span>agit</span>,<br>vérifie, et apprend de ses erreurs</h1>
  <div class=rule></div>
  <p>Objectif → outils → vérification → livrable. Pas une démo : un agent de production, ramené à une boucle exécutable en deux commandes.</p>
  <div class=foot>Vigie · docker run holloow313/agent-computer-challenge-high-end · 9 tests · aucune clé requise</div>
</body></html>"""

END = f"""<!doctype html><html lang=fr><meta charset=utf-8><style>{BASE_CSS}
  h1 {{ font-size: 40px; margin-bottom: 26px; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ font: 20px/2.1 ui-monospace, monospace; color: #c3cbdb; }}
  li b {{ color: #5b8cff; font-weight: 600; }}
  .foot {{ margin-top: 34px; font: 15px/1.7 ui-monospace, monospace; color: #5e6675; }}
</style>
<body>
  <h1>Vigie, ce qu'il faut retenir</h1>
  <ul>
    <li><b>·</b> une boucle agentique réelle, journal JSON, bac à sable par run</li>
    <li><b>·</b> mémoire procédurale : 6 étapes / 1 erreur → 4 étapes / 0 erreur</li>
    <li><b>·</b> mesures reproductibles : réussite, latence, coût par 1 000 tâches</li>
    <li><b>·</b> local d'abord : Ollama, LM Studio, vLLM, cloud en option</li>
  </ul>
  <div class=foot>github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End · MIT</div>
</body></html>"""


def numbers_html() -> str:
    reports = sorted(glob.glob(str(BENCH / "mesures-*.json")))
    rows = []
    meta = ""
    verdict = "GPU actuel : 3 Go de VRAM, modèles locaux, aucun appel sortant."
    if reports:
        data = json.loads(Path(reports[-1]).read_text(encoding="utf-8"))
        meta = f"{data['tasks']} tâches vérifiables · {data['repeat']} passe · notation exacte"
        if len(data["results"]) >= 2:
            fast, slow = sorted(data["results"], key=lambda r: r["p50_s"])[:2]
            if fast["p50_s"] > 0:
                ratio = slow["p50_s"] / fast["p50_s"]
                verdict += (
                    f"<br>{fast['model']} répond en {fast['p50_s']:.2f} s mais réussit "
                    f"{fast['ok_rate']:.0f} % ; {slow['model']} réussit {slow['ok_rate']:.0f} % "
                    f"mais coûte {ratio:.0f}× plus de temps par réponse."
                )
        for r in data["results"]:
            cost = "0 €" if r["cost_per_1k_tasks"] == 0 else f"{r['cost_per_1k_tasks']:.2f} €"
            rows.append(
                f"<tr><td>{r['target']}</td>"
                f"<td class=num>{r['model']}</td>"
                f"<td class='num ok'>{r['ok_rate']:.0f} %</td>"
                f"<td class=num>{r['p50_s']:.2f} s</td>"
                f"<td class=num>{r['p95_s']:.2f} s</td>"
                f"<td class=num>{cost}</td></tr>"
            )
    return f"""<!doctype html><html lang=fr><meta charset=utf-8><style>{BASE_CSS}
  h1 {{ font-size: 34px; margin-bottom: 8px; }}
  .sub {{ color: #8a94a8; font: 16px/1.5 ui-monospace, monospace; margin-bottom: 30px; }}
  table {{ width: 100%; border-collapse: collapse; font: 17px/1.9 ui-monospace, monospace; }}
  th {{ text-align: left; color: #7f8ba1; font-weight: 500; font-size: 13px; letter-spacing: .1em; text-transform: uppercase; border-bottom: 1px solid #232a38; padding-bottom: 10px; }}
  td {{ border-bottom: 1px solid #171c27; color: #d5dcea; }}
  .num {{ text-align: right; }}
  tr:last-child td {{ border-bottom: 0; }}
  .note {{ margin-top: 28px; color: #6f7a90; font: 14px/1.7 ui-monospace, monospace; }}
</style>
<body>
  <h1>Mesures sur la machine actuelle</h1>
  <div class=sub>{meta or "mesures locales"}</div>
  <table>
    <tr><th>Cible</th><th>Modèle</th><th class=num>Réussite</th><th class=num>p50</th><th class=num>p95</th><th class=num>Coût</th></tr>
    {''.join(rows)}
  </table>
  <div class=note>{verdict}</div>
</body></html>"""


def shot(page, html: str, name: str) -> None:
    path = OUT / f"{name}.png"
    page.set_content(html, wait_until="load")
    page.wait_for_timeout(250)
    page.screenshot(path=str(path))
    print("carton:", path)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        shot(page, TITLE, "01-titre")
        shot(page, numbers_html(), "03-chiffres")
        shot(page, END, "04-fin")
        browser.close()


if __name__ == "__main__":
    main()
