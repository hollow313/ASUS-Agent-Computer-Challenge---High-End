"""La vidéo du crash et de la reprise, faite avec la sortie réelle du terminal.

Aucune image inventée : chaque ligne affichée vient de `docs/runs/crash-resume/journal-avant-kill.log`
ou de `journal-apres-reprise.log`, produits par deux exécutions réelles. Le montage ajoute seulement le
rythme (temps d'affichage) et un carton rouge pour le `kill -9`.

    python3 video/crash_demo.py

Sortie : `docs/video/vigie-crash-resume.mp4`, moins de 45 secondes.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "docs" / "runs" / "crash-resume"
DEST = REPO / "docs" / "video" / "vigie-crash-resume.mp4"
W, H = 1280, 720

HTML = """<!doctype html><html lang=fr><meta charset=utf-8><style>
  * { box-sizing: border-box; margin: 0 }
  body { width: __W__px; height: __H__px; background: #0b0e14; color: #c9d1e0; padding: 34px 38px;
    font: 17px/1.62 ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
  .barre { display: flex; gap: 8px; margin-bottom: 20px; align-items: center; }
  .dot { width: 11px; height: 11px; border-radius: 50%; }
  .t { color: #5e6675; font-size: 12px; letter-spacing: .16em; text-transform: uppercase; margin-left: 8px }
  .line { white-space: pre-wrap; }
  .ok { color: #3ecf8e } .err { color: #f5a524 } .dim { color: #7f8ba1 }
  .kill { color: #ff6b6b; font-weight: 700 }
  .big { font-size: 40px; letter-spacing: -.02em; color: #e6ebf5; margin: 26px 0 10px; }
  .sub { color: #7f8ba1; font-size: 16px }
</style><body>
<div class="barre">
  <span class="dot" style="background:#ff5f57"></span>
  <span class="dot" style="background:#febc2e"></span>
  <span class="dot" style="background:#28c840"></span>
  <span class="t">__TITLE__</span>
</div>
__BODY__
</body></html>"""


def lines(path: Path, prefix: str) -> list[str]:
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.rstrip()
        if not text or text.startswith(("▸ scénario", "▸ objectif", "▸ espace", "▸ journal")):
            continue
        if text.startswith("▸"):
            text = text.replace("▸", "›")
        out.append((prefix + text) if prefix else text)
    return out


def frame(body: str, title: str) -> str:
    return HTML.replace("__W__", str(W)).replace("__H__", str(H)).replace("__TITLE__", title).replace("__BODY__", body)


def main() -> None:
    avant = lines(RUNS / "journal-avant-kill.log", "")
    apres = lines(RUNS / "journal-apres-reprise.log", "")
    avant = [line for line in avant if "rss_rank" in line or "passe" in line][:2]
    apres = [line for line in apres if "[0" in line or "statut" in line or "livrables" in line][:4]

    frames: list[tuple[str, float]] = []
    frames.append((frame(
        '<div class="big">Un agent qu\'on tue en pleine exécution.</div>'
        '<div class="sub">run réel · cyber-brief · modèle local · carte de 3 Go</div>', "vigie · crash et reprise"), 2.4))
    for index in range(1, len(avant) + 1):
        body = "".join(f'<div class="line">{line}</div>' for line in avant[:index])
        frames.append((frame(body, "terminal · run en cours"), 1.5))
    frames.append((frame(
        '<div class="line dim">$ kill -9 $(pgrep -f "agentdemo run")</div>'
        '<div class="line kill">processus tué</div>'
        '<div class="sub" style="margin-top:24px">aucune étape rejouée · état écrit après chaque étape</div>',
        "terminal · coupure"), 2.2))
    for index in range(1, len(apres) + 1):
        body = '<div class="line dim">$ python3 -m agentdemo run --scenario cyber-brief --resume ...</div>'
        body += "".join(f'<div class="line">{line}</div>' for line in apres[:index])
        frames.append((frame(body, "terminal · reprise"), 1.7))
    frames.append((frame(
        '<div class="big">Il reprend à l\'étape suivante,<br>et le livrable est écrit.</div>'
        '<div class="sub">journal : docs/runs/crash-resume/ · aucune étape rejouée</div>',
        "vigie · reprise"), 3.0))

    DEST.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": W, "height": H})
            concat = []
            for index, (html, seconds) in enumerate(frames, start=1):
                page.set_content(html, wait_until="load")
                page.wait_for_timeout(60)
                shot = tmpdir / f"f{index:03d}.png"
                page.screenshot(path=str(shot))
                concat += [f"file '{shot}'", f"duration {seconds}"]
            browser.close()
        concat.append(f"file '{tmpdir / f'f{len(frames):03d}.png'}'")
        listing = tmpdir / "list.txt"
        listing.write_text("\n".join(concat) + "\n", encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             str(DEST)],
            check=True, capture_output=True,
        )
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(DEST)],
        check=True, capture_output=True, text=True,
    )
    print(f"vidéo : {DEST} · {float(json.loads(probe.stdout)['format']['duration']):.1f} s · {DEST.stat().st_size // 1024} Ko")


if __name__ == "__main__":
    main()
