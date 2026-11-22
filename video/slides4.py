"""Cartons de la vidéo finale (1280 x 720), captures réelles incluses.

Chaque carton correspond à un paragraphe de la voix off : `video/narration-presentation.txt`.
Les captures d'écran du dépôt sont embarquées en base64 pour que le rendu soit autonome.
"""

from __future__ import annotations

import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("/data/agent-computer-challenge/video/slides4")
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
  <h1>Vigie<br><span>un agent qui prend le quart</span></h1>
  <p>Objectif, outils, livrable vérifié. Il écrit, il relit, il apprend, et il reprend après un crash.</p>
  <div class=foot>github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End · replay déterministe, sans clé ni réseau</div>
"""
)

SLIDES["02-limite"] = base(
    """
  <div class=kicker>Ce qui bloque aujourd'hui</div>
  <h1>3 Go de VRAM,<br><span>7 milliards de paramètres, une erreur sur deux</span></h1>
  <div class=big>
    <div class=stat><b>60 %</b><span>7B Q4, rapide et faux</span></div>
    <div class=stat><b>90 %</b><span>8B Q4, juste mais lent</span></div>
    <div class=stat><b>0</b><span>sous-agent en parallèle</span></div>
  </div>
  <p>Le modèle qui comprend les tâches ambiguës ne rentre pas, et le contexte reste trop court pour lire un dossier entier.</p>
  <div class=foot>mesures du 21/11/2026 · python3 -m agentdemo fit --vram 32</div>
"""
)

SLIDES["03-scenarios"] = base(
    """
  <div class=kicker>Sept scénarios, sept livrables</div>
  <h1>Des fichiers, pas des captures</h1>
  <table>
    <tr><th>scénario</th><th>ce qu'il fait</th><th>livrable</th></tr>
    <tr><td>cyber-brief</td><td>trois flux, hiérarchie, rédaction</td><td class=ok>briefing.md</td></tr>
    <tr><td>dataset-report</td><td>CSV, calcul, graphique</td><td class=ok>synthese.md, graphique.svg</td></tr>
    <tr><td>inbox-triage</td><td>boîte IMAP, classement</td><td class=ok>rapport-tri.md</td></tr>
    <tr><td>local-audit</td><td>journaux, ports, permissions</td><td class=ok>RAPPORT-AUDIT.md</td></tr>
    <tr><td>delegation</td><td>trois sous-agents, agrégation</td><td class=ok>comparatif.md</td></tr>
    <tr><td>self-repair</td><td>réparation, procédure apprise</td><td class=ok>veille.md</td></tr>
    <tr><td>revue-contradictoire</td><td>jet refusé, corrigé, accepté</td><td class=ok>synthese.md</td></tr>
  </table>
  <div class=foot>journal horodaté par run · replay sans réseau, live sur modèle local</div>
"""
)

SLIDES["04-memoire"] = base(
    """
  <div class=kicker>Mémoire procédurale</div>
  <h1>Il n'est pas plus intelligent,<br><span>il est plus économe</span></h1>
  <pre>passe 1   6 étapes   1 erreur   <span class=warn>leçon écrite avec son contrat</span>
passe 2   4 étapes   0 erreur   <span class=ok>procédure relue et appliquée</span>
fichier renommé        contrat cassé   <span class=warn>procédure retirée</span></pre>
  <p>Une leçon morte ne pollue pas le run suivant : la mémoire a un cycle de vie, pas un prompt plus long.</p>
  <div class=foot>skill_write, skill_recall, skill_revise, skill_prune · journal dans runs/&lt;id&gt;/journal.json</div>
"""
)

SLIDES["05-delegation"] = base(
    """
  <div class=kicker>Orchestration</div>
  <h1>Trois zones, trois sous-agents,<br><span>un parent qui relit</span></h1>
  <pre>parent  →  spawn_agent(nord)   →  delegations/nord/resume.md
        →  spawn_agent(sud)    →  delegations/sud/resume.md
        →  spawn_agent(ouest)  →  delegations/ouest/resume.md
        →  lecture des trois, puis comparatif.md</pre>
  <p>Chaque enfant a son budget, son journal et son dossier. La confiance se vérifie, elle ne se déclare pas.</p>
  <div class=foot>profondeur limitée · budget par enfant · aucun accès au disque du parent</div>
"""
)

SLIDES["06-routage"] = base(
    """
  <div class=kicker>Routage des modèles</div>
  <h1>Une politique écrite,<br><span>pas un routeur magique</span></h1>
  <table>
    <tr><th>règle</th><th>cible</th><th>raison</th></tr>
    <tr><td>sensitive</td><td>local-gros</td><td>ce qui ne doit pas sortir reste en local</td></tr>
    <tr><td>keyword tri</td><td>local-rapide</td><td>tâche mécanique, petit modèle</td></tr>
    <tr><td>défaut</td><td>local-gros</td><td>le local le plus capable</td></tr>
  </table>
  <p>Une cible peut déclarer un repli : si la première ne répond pas, une bascule, un événement, et la suite continue.</p>
  <div class=foot>override manuel journalisé · chaque décision garde sa raison</div>
"""
)

SLIDES["07-robustesse"] = base(
    """
  <div class=kicker>Robustesse</div>
  <h1>Reprise, revue, autorisations</h1>
  <table>
    <tr><th>mécanisme</th><th>ce que ça change</th></tr>
    <tr><td>state.json</td><td>après chaque étape, en écriture atomique : un run tué reprend sans rejouer</td></tr>
    <tr><td>revue</td><td>un second modèle relit le livrable et peut le refuser, motifs à l'appui</td></tr>
    <tr><td>accord</td><td>par scénario, décoché par défaut : les tâches planifiées ne bloquent jamais</td></tr>
    <tr><td>masquage</td><td>les valeurs sensibles n'apparaissent pas dans les journaux</td></tr>
  </table>
  <div class=foot>--resume, POST /api/runs/&lt;id&gt;/resume, bouton reprendre · deux relectures maximum</div>
"""
)

SLIDES["08-exploitation"] = base(
    """
  <div class=kicker>Exploitation</div>
  <h1>Tout se règle depuis l'interface</h1>
  <table>
    <tr><th>ce qu'on veut faire</th><th>où</th></tr>
    <tr><td>créer, modifier, masquer un scénario</td><td>page principale</td></tr>
    <tr><td>régler réseau, dossier, flux, accord</td><td>éditeur de scénario</td></tr>
    <tr><td>ajouter un serveur MCP et le tester</td><td>réglages</td></tr>
    <tr><td>planifier une veille à 8 h</td><td>tâches planifiées</td></tr>
    <tr><td>choisir le modèle ou forcer une cible</td><td>routage</td></tr>
  </table>
  <p>Chaque action a son équivalent en ligne de commande, et le mot de passe reste dans le volume, en 600.</p>
  <div class=foot>MCP : poignée de main réelle, outils listés · catalogue d'outils vérifié par empreinte</div>
"""
)

SLIDES["09-chiffres"] = base(
    """
  <div class=kicker>Mesuré, pas affirmé</div>
  <h1>Ce que 3 Go permettent</h1>
  <table>
    <tr><th>cible</th><th>où</th><th>réussite</th><th>p50</th><th>coût / 1 000</th></tr>
    <tr><td>Qwen 2.5 Coder 7B, Q4</td><td>local</td><td>60 %</td><td>0,75 s</td><td>0 €</td></tr>
    <tr><td>Qwen3 VL 8B, Q4</td><td>local</td><td class=ok>90 %</td><td>0,67 s</td><td>0 €</td></tr>
    <tr><td>Gemini 3.8 Flash</td><td>cloud</td><td class=ok>100 %</td><td>4,17 s</td><td>0,07 €</td></tr>
    <tr><td>Claude Opus 5.5</td><td>cloud</td><td>—</td><td>—</td><td class=warn>0,38 €</td></tr>
    <tr><td>GPT-5.5 Pro</td><td>cloud</td><td>—</td><td>—</td><td class=warn>3,01 €</td></tr>
  </table>
  <p>Le local est gratuit mais se trompe une fois sur deux. Le cloud est juste mais sort vos données, et le haut de gamme coûte quarante-trois fois l'entrée de gamme.</p>
  <div class=foot>dix tâches, température 0, notation exacte · rapport complet dans docs/mesures/</div>
"""
)

SLIDES["10-carte"] = base(
    """
  <div class=kicker>Ce que la carte change</div>
  <h1>32 Go : un 32B en 4 bits,<br><span>30,4 Go de poids, 1,6 Go de marge</span></h1>
<pre>7,6 B   Q8   11,7 Go   marge 20,3
14,7 B  Q8   20,9 Go   marge 11,1
23,6 B  Q6   26,9 Go   marge  5,1
32,8 B  Q4   30,4 Go   marge  1,6   <span class=ok>← la cible</span>
70,6 B  Q4   56,0 Go   ne rentre pas</pre>
  <p>Un dossier entier, un raisonnement long, des sous-agents en parallèle, et ce qui ne doit pas sortir ne sort plus.</p>
  <div class=foot>github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End · 64 tests · deux commandes, aucune clé</div>
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
