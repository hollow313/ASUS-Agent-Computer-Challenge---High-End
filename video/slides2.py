"""Cartons de la seconde vidéo : orchestration de sous-agents."""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("/data/agent-computer-challenge/video/slides2")
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1280, 720

BASE = """
  * { box-sizing: border-box; margin: 0; }
  body { width: %dpx; height: %dpx; background: #0b0e14; color: #e6ebf5; margin: 0;
    font: 20px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 64px 72px; display: flex; flex-direction: column; justify-content: center; }
  .kicker { font: 15px/1 ui-monospace, monospace; letter-spacing: .22em; text-transform: uppercase;
    color: #5b8cff; margin-bottom: 24px; }
  h1 { font-size: 52px; line-height: 1.15; margin-bottom: 20px; font-weight: 680; }
  h1 span { color: #5b8cff; }
  p { color: #9aa4b8; font-size: 20px; max-width: 940px; }
  .foot { margin-top: 40px; font: 14px/1.6 ui-monospace, monospace; color: #5e6675; }
  pre { font: 16px/1.75 ui-monospace, monospace; color: #c3cbdb; background: #10141c;
    border: 1px solid #232a38; border-radius: 10px; padding: 22px 26px; }
  .ok { color: #3ecf8e; }
  ul { list-style: none; padding: 0; font: 19px/2.05 ui-monospace, monospace; color: #c3cbdb; }
  ul b { color: #5b8cff; font-weight: 600; }
""" % (W, H)

TITLE = f"""<!doctype html><html lang=fr><meta charset=utf-8><style>{BASE}
  </style>
<body>
  <div class=kicker>Vigie · démonstration 2</div>
  <h1>Orchestration de <span>sous-agents</span></h1>
  <p>Le parent ne fait pas le travail : il délègue trois zones à trois sous-agents, chacun avec son
  budget et son répertoire, puis relit leurs livrables avant d'agréger.</p>
  <div class=foot>docker run holloow313/asus-agent-computer-challenge-high-end · scénario delegation</div>
</body></html>"""

TREE = f"""<!doctype html><html lang=fr><meta charset=utf-8><style>{BASE}
  h1 {{ font-size: 32px; margin-bottom: 22px; }}
</style>
<body>
  <h1>Budget cloisonné, artefacts rangés</h1>
<pre>parent (6 étapes, budget 10)
├── <span class=ok>sous-agent nord</span>   3 étapes  → delegations/nord/resume.md
├── <span class=ok>sous-agent sud</span>    3 étapes  → delegations/sud/resume.md
├── <span class=ok>sous-agent ouest</span>  3 étapes  → delegations/ouest/resume.md
└── relecture des trois notes, puis agrégation → comparatif.md</pre>
  <p class=foot>Un sous-agent bavard ne peut pas épuiser le budget de son parent. Le parent vérifie
  ce qu'il reçoit au lieu de faire confiance à un résumé.</p>
</body></html>"""

END = f"""<!doctype html><html lang=fr><meta charset=utf-8><style>{BASE}
  h1 {{ font-size: 38px; margin-bottom: 24px; }}
</style>
<body>
  <h1>Ce que montre cette démonstration</h1>
  <ul>
    <li><b>·</b> trois objectifs indépendants traités en sous-agents</li>
    <li><b>·</b> budget et journal cloisonnés par délégation</li>
    <li><b>·</b> le parent relit avant d'agréger</li>
    <li><b>·</b> et la mémoire procédurale continue de tourner en fond</li>
  </ul>
  <div class=foot>github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End</div>
</body></html>"""


def shot(page, html: str, name: str) -> None:
    path = OUT / f"{name}.png"
    page.set_content(html, wait_until="load")
    page.wait_for_timeout(200)
    page.screenshot(path=str(path))
    print("carton:", path)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        shot(page, TITLE, "01-titre")
        shot(page, TREE, "02-arbre")
        shot(page, END, "03-fin")
        browser.close()


if __name__ == "__main__":
    main()
