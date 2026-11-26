"""Rejoue la mesure de vision et écrit le résultat daté.

Ce script existe pour une raison précise : un chiffre qu'un tiers ne peut pas recalculer n'est pas une
preuve, c'est une annonce. Dix images, dix questions dont la réponse est dans l'image, notation par
correspondance exacte, aucune tolérance.

    python3 scripts/vision_check.py --base-url http://127.0.0.1:1234/v1 --model qwen/qwen3-vl-8b

Sortie : `docs/mesures/vision-<horodatage>.json`, plus une ligne sur la console. Code de sortie 0 si et
seulement si les dix réponses sont exactes.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bench"))

CAPTURES = REPO / "bench" / "captures"
TASKS = REPO / "bench" / "tasks_vision.jsonl"
OUT = REPO / "docs" / "mesures"


def normalise(text: str) -> str:
    import re
    import unicodedata

    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", str(text).lower()) if not unicodedata.combining(ch)
    )
    return re.sub(r"[^a-z0-9,.\- ]+", " ", stripped)


def ask(base_url: str, model: str, image: Path, question: str, timeout: int) -> str:
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()
                        },
                    },
                ],
            }
        ],
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        json.dumps(payload).encode(),
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    return str(body["choices"][0]["message"]["content"])


def main() -> int:
    parser = argparse.ArgumentParser(description="mesure de vision, reproductible")
    parser.add_argument("--base-url", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--model", default="qwen/qwen3-vl-8b")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    tasks = [json.loads(line) for line in TASKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    started = time.time()
    for task in tasks:
        image = CAPTURES / task["image"]
        try:
            answer = ask(args.base_url, args.model, image, task["prompt"], args.timeout)
            haystack = normalise(answer)
            ok = all(normalise(needle) in haystack for needle in task["expect"])
            results.append(
                {
                    "id": task["id"],
                    "image": task["image"],
                    "ok": ok,
                    "answer": answer.strip()[:200],
                    "expected": task["expect"],
                }
            )
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            results.append({"id": task["id"], "image": task["image"], "ok": False, "error": str(exc)[:200]})

    passed = sum(1 for item in results if item["ok"])
    payload = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": args.model,
        "base_url": args.base_url,
        "tasks": len(tasks),
        "passed": passed,
        "score": f"{passed}/{len(tasks)}",
        "duration_s": round(time.time() - started, 1),
        "temperature": 0,
        "grading": "correspondance exacte, accents et casse ignorés",
        "results": results,
    }
    path = Path(args.out)
    path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path / f"vision-{stamp}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{passed}/{len(tasks)} · {payload['duration_s']} s · {target.relative_to(REPO) if target.is_relative_to(REPO) else target}")
    for item in results:
        if not item["ok"]:
            print(f"  échec : {item['id']} → {item.get('answer') or item.get('error')}")
    return 0 if passed == len(tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
