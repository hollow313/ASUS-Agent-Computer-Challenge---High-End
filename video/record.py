"""Capture l'interface de la démo en screencast CDP, pour le montage vidéo.

Produit des frames JPEG horodatées dans /data/agent-computer-challenge/video/frames
et un fichier `timeline.json` (durée de chaque frame) pour reconstruire le rythme réel.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("/data/agent-computer-challenge/video/frames")
APP = "http://127.0.0.1:8092/"
W, H = 1280, 720


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    frames: list[tuple[str, float]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        client = page.context.new_cdp_session(page)

        def on_frame(params: dict) -> None:
            name = f"f{len(frames):05d}.jpg"
            (OUT / name).write_bytes(base64.b64decode(params["data"]))
            frames.append((name, time.time()))
            client.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

        page.goto(APP, wait_until="networkidle")
        page.wait_for_selector(".scenario")
        page.wait_for_timeout(2500)

        client.on("Page.screencastFrame", on_frame)
        client.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 85, "maxWidth": W, "maxHeight": H, "everyNthFrame": 1},
        )

        # --- scène 1 : briefing cyber (replay) ---
        page.wait_for_timeout(2500)
        page.click("#run")
        for _ in range(40):
            page.wait_for_timeout(200)
            if "done" in page.inner_text("#statusText"):
                break
        page.wait_for_timeout(3000)
        page.evaluate("window.scrollTo({top: 420, behavior: 'smooth'})")
        page.wait_for_timeout(5000)
        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        page.wait_for_timeout(1500)

        # --- scène 2 : auto-réparation, deux passes ---
        page.click("text=Auto-réparation → procédure apprise")
        page.wait_for_timeout(1200)
        page.click("#run")
        for _ in range(60):
            page.wait_for_timeout(200)
            if "done" in page.inner_text("#statusText"):
                break
        page.wait_for_timeout(3500)
        page.evaluate("document.querySelector('.recap')?.scrollIntoView({block: 'center', behavior: 'smooth'})")
        page.wait_for_timeout(6000)
        page.evaluate("document.querySelector('#skills')?.scrollIntoView({block: 'center', behavior: 'smooth'})")
        page.wait_for_timeout(4500)

        client.send("Page.stopScreencast")
        browser.close()

    stamps = [stamp for _, stamp in frames]
    timeline = []
    for index, (name, _) in enumerate(frames):
        end = stamps[index + 1] if index + 1 < len(stamps) else stamps[-1] + 0.08
        timeline.append({"file": name, "duration": max(0.04, round(end - stamps[index], 3))})

    (OUT.parent / "timeline.json").write_text(json.dumps(timeline, indent=1), encoding="utf-8")
    total = sum(item["duration"] for item in timeline)
    print(f"{len(timeline)} frames · {total:.1f} s de capture")

    concat = OUT.parent / "concat.txt"
    # le demuxer concat veut des paires file/duration, la dernière répétée
    body = []
    for item in timeline:
        body.append(f"file '{OUT / item['file']}'")
        body.append(f"duration {item['duration']}")
    body.append(f"file '{OUT / timeline[-1]['file']}'")
    concat.write_text("\n".join(body) + "\n", encoding="utf-8")

    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            str(OUT.parent / "02-interface.mp4"),
        ],
        check=True,
        capture_output=True,
    )
    print("→ /data/agent-computer-challenge/video/02-interface.mp4")


if __name__ == "__main__":
    main()
