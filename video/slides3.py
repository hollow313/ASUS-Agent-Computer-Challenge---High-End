"""Cartons de la vidéo de présentation (1280 x 720), captures réelles incluses.

Chaque carton correspond à un paragraphe de la voix off : `video/narration-presentation.txt`.
Les captures d'écran du dépôt sont embarquées en base64 pour que le rendu soit autonome.
"""

from __future__ import annotations

import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("/data/agent-computer-challenge/video/slides3")
REPO = Path(__file__).resolve().parent.parent
W, H = 1280, 720

BASE = """
  * { box-sizing: border-box; margin: 0; }
  body { width: __W__px; height: __H__px; background: #0b0e14; color: #e6ebf5; margin: 0;
    font: 20px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 54px 64px; display: flex; flex-direction: column; justify-content: center; }
  .kicker { font: 14px/1 ui-monospace, monospace; letter-spacing: .22em; text-transform: uppercase;
    color: #5b8cff; margin-bottom: 18px; }
  h1 { font-size: 46px; line-height: 1.12; margin-bottom: 16px; font-weight: 680; }
  h1 span { color: #5b8cff; }
  p { color: #9aa4b8; font-size: 19px; max-width: 1000px; }
  .foot { margin-top: 26px; font: 13px/1.6 ui-monospace, monospace; color: #5e6675; }
  pre { font: 15px/1.65 ui-monospace, monospace; color: #c3cbdb; background: #10141c;
    border: 1px solid #232a38; border-radius: 10px; padding: 18px 22px; }
  .ok { color: #3ecf8e; } .accent { color: #5b8cff; } .warn { color: #f5a524; }
  .big { display: flex; gap: 42px; margin: 18px 0 6px; }
  .stat { }
  .stat b { display: block; font: 600 54px/1 ui-monospace, monospace; color: #e6ebf5; }
  .stat span { font: 13px/1.5 ui-monospace, monospace; color: #7f8ba1; }
  table { border-collapse: collapse; font: 15px/1.7 ui-monospace, monospace; width: 100%; }
  th { text-align: left; color: #7f8ba1; font-weight: 500; border-bottom: 1px solid #232a38; padding: 0 14px 8px 0; }
  td { border-bottom: 1px solid #171c27; padding: 7px 14px 7px 0; color: #c3cbdb; }
  .shot { border: 1px solid #2a3346; border-radius: 12px; overflow: hidden; background: #0d1119; position: relative; }
  .shot::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 150px;
    background: linear-gradient(to bottom, rgba(11,14,20,0) 0%, rgba(11,14,20,.72) 55%, #0b0e14 100%); }
  .shot img { display: block; width: 100%; height: 100%; object-fit: cover; object-position: top left; }
  .frame { height: 470px; }
"""


def base(body: str, extra: str = "") -> str:
    css = BASE.replace("__W__", str(W)).replace("__H__", str(H)) + extra
    return f"<!doctype html><html lang=fr><meta charset=utf-8><style>{css}</style><body>{body}</body></html>"


def shot(name: str) -> str:
    """Capture du dépôt, embarquée en base64 pour un rendu autonome."""
    raw = (REPO / "docs" / name).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode()


SLIDES: dict[str, str] = {}

SLIDES["01-titre"] = base(
    """
  <div class=kicker>Candidature ASUS Agent Computer Challenge · High-End</div>
  <h1>Vigie : un agent qui<br><span>prend le quart</span></h1>
  <p>Il reçoit un objectif, choisit ses outils, agit sur de vrais fichiers, relit ce qu'il a produit,
  et apprend de ses erreurs. Sans clé, sans réseau, sans dépendance.</p>
  <div class=foot>holloow313/asus-agent-computer-challenge-high-end · MIT · 32 tests</div>
"""
)

SLIDES["02-limite"] = base(
    """
  <div class=kicker>Le point de départ</div>
  <h1>3 Go de mémoire vidéo</h1>
  <div class=big>
    <div class=stat><b>7 B</b><span>le plus gros modèle<br>qui rentre, en 4 bits</span></div>
    <div class=stat><b>60 %</b><span>de réussite sur dix<br>tâches vérifiables</span></div>
    <div class=stat><b>0,40 s</b><span>de latence médiane</span></div>
  </div>
  <p style="margin-top:22px">Rapide, gratuit, et faux une fois sur deux. Le modèle qui comprend les tâches
  ambiguës ne rentre pas. Les sous-agents ne tournent pas en parallèle.</p>
  <div class=foot>mesures du 20/11/2026 · dix tâches · notation par correspondance exacte</div>
"""
)

SLIDES["03-scenarios"] = base(
    """
  <div class=kicker>Cinq scénarios, cinq livrables réels</div>
  <h1>Il écrit, il relit, il conclut</h1>
  <div class="shot frame" style="margin-top:10px"><img src="%s"></div>
  <div class=foot>briefing daté · synthèse chiffrée et graphique · tri de mail · auto-réparation · orchestration</div>
"""
    % shot("screenshot-run.png")
)

SLIDES["04-memoire"] = base(
    """
  <div class=kicker>Mémoire procédurale</div>
  <h1>6 étapes et 1 erreur<br>deviennent <span>4 étapes et 0 erreur</span></h1>
  <div class="shot frame" style="margin-top:10px"><img src="%s"></div>
  <div class=foot>chaque procédure porte un contrat de vérification : si la cible change, elle est retirée au lieu d'être appliquée</div>
"""
    % shot("screenshot-selfrepair.png")
)

SLIDES["05-delegation"] = base(
    """
  <div class=kicker>Orchestration</div>
  <h1>Trois zones, trois sous-agents</h1>
<pre>parent (8 étapes, mode réel)          budget cloisonné, journal séparé
├── <span class=ok>sous-agent zone-nord</span>   → livrable analysé
├── <span class=ok>sous-agent zone-ouest</span>  → livrable analysé
├── <span class=ok>sous-agent zone-sud</span>    → livrable analysé
└── relecture des trois, puis <span class=accent>comparatif.md</span></pre>
  <p style="margin-top:20px">Un sous-agent bavard ne peut pas épuiser le budget de son parent.
  Le parent vérifie ce qu'il reçoit au lieu de faire confiance à un résumé.</p>
  <div class=foot>profondeur bornée à trois niveaux · relance d'un même sous-agent refusée</div>
"""
)

SLIDES["06-routage"] = base(
    """
  <div class=kicker>Routage des modèles</div>
  <h1>Le bon modèle pour la bonne tâche</h1>
  <div class="shot frame" style="margin-top:10px"><img src="%s"></div>
  <div class=foot>deux instances locales, deux clouds, un mélange : la règle décide, la décision est journalisée</div>
"""
    % shot("screenshot-routing.png")
)

SLIDES["07-exploitation"] = base(
    """
  <div class=kicker>Exploitation</div>
  <h1>Des entrées réelles, un planning</h1>
  <div class="shot frame" style="margin-top:10px"><img src="%s"></div>
  <div class=foot>dossier CSV · boîte IMAP · veille tous les matins à 08:00 · mot de passe jamais renvoyé par l'API</div>
"""
    % shot("screenshot-settings.png")
)

SLIDES["08-chiffres"] = base(
    """
  <div class=kicker>Mesuré, pas affirmé</div>
  <h1>Ce que 3 Go permettent</h1>
  <table>
    <tr><th>cible</th><th>où</th><th>réussite</th><th>p50</th><th>p95</th><th>coût / 1 000</th></tr>
    <tr><td>Qwen 2.5 Coder 7B, Q4</td><td>local</td><td>60 %</td><td>0,40 s</td><td>0,64 s</td><td>0 €</td></tr>
    <tr><td>Qwen3 VL 8B, Q4</td><td>local</td><td class=ok>90 %</td><td>11,6 s</td><td>28,7 s</td><td>0 €</td></tr>
    <tr><td>DeepSeek Chat</td><td>cloud</td><td class=ok>100 %</td><td>0,93 s</td><td>1,25 s</td><td class=warn>0,02 €</td></tr>
  </table>
  <p style="margin-top:24px">Le local est gratuit mais se trompe ou coûte trente fois plus de temps.
  Le cloud est juste mais sort vos données. Le modèle intermédiaire n'existe pas dans 3 Go.</p>
  <div class=foot>dix tâches, température 0, notation exacte · rapport complet dans docs/mesures/</div>
"""
)

SLIDES["09-fin"] = base(
    """
  <div class=kicker>Ce que la carte change</div>
  <h1>32 Go : un 32B en 4 bits,<br><span>30,4 Go de poids, 1,6 Go de marge</span></h1>
<pre>7,6 B   Q8   11,7 Go   marge 20,3
14,7 B  Q8   20,9 Go   marge 11,1
23,6 B  Q6   26,9 Go   marge  5,1
32,8 B  Q4   30,4 Go   marge  1,6   <span class=ok>← la cible</span>
70,6 B  Q4   56,0 Go   ne rentre pas</pre>
  <p style="margin-top:18px">Un dossier entier, un raisonnement de trente étapes, des sous-agents en parallèle,
  et ce qui ne doit pas sortir ne sort plus.</p>
  <div class=foot>github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End · docker run holloow313/... · les limites sont écrites</div>
"""
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for name, html in SLIDES.items():
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(250)
            path = OUT / f"{name}.png"
            page.screenshot(path=str(path))
            print("carton:", path.name)
        browser.close()


if __name__ == "__main__":
    main()
