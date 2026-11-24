"""Banc de mesure : le même agent, trois questions par modèle.

Trois chiffres que le jury peut vérifier, et qui décident de l'intérêt d'un Agent
Computer plutôt que d'une API :

1. **qualité**, le modèle réussit-il les tâches réelles de l'agent (extraction,
   classement, calcul) ? Noté par comparaison exacte, pas à l'appréciation ;
2. **latence**, p50 / p95 par tâche, en secondes ;
3. **coût**, € pour 1 000 exécutions de la tâche, calculé sur les tokens réellement
   consommés et un prix au million de tokens.

Aucune dépendance, aucun framework. Tout endpoint compatible OpenAI convient :
Ollama, LM Studio, vLLM, ou une API distante.

    python3 bench/bench.py --targets bench/targets.example.json
    python3 bench/bench.py --target "local=http://localhost:11434/v1|qwen2.5-coder:7b"
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import unicodedata
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BENCH_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BENCH_DIR / "reports"
TASKS_FILE = BENCH_DIR / "tasks.jsonl"
VISION_TASKS_FILE = BENCH_DIR / "tasks_vision.jsonl"
CAPTURES_DIR = BENCH_DIR / "captures"
PRICES_FILE = BENCH_DIR / "prices.json"


@dataclass
class Target:
    name: str
    base_url: str
    model: str
    api_key: str = ""
    label: str = "cloud"
    price_in: float = 0.0  # € / million de tokens d'entrée
    price_out: float = 0.0  # € / million de tokens de sortie

    @property
    def free(self) -> bool:
        return self.price_in == 0.0 and self.price_out == 0.0


@dataclass
class Sample:
    task_id: str
    ok: bool
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    reply: str = ""
    error: str = ""


@dataclass
class TargetResult:
    target: Target
    samples: list[Sample] = field(default_factory=list)

    @property
    def ok_rate(self) -> float:
        return 100.0 * sum(1 for s in self.samples if s.ok) / max(1, len(self.samples))

    @property
    def p50(self) -> float:
        return statistics.median([s.latency_s for s in self.samples]) if self.samples else 0.0

    @property
    def p95(self) -> float:
        latencies = sorted(s.latency_s for s in self.samples)
        if not latencies:
            return 0.0
        index = min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))
        return latencies[index]

    @property
    def tokens_out_per_s(self) -> float:
        total = sum(s.completion_tokens for s in self.samples)
        elapsed = sum(s.latency_s for s in self.samples)
        return total / elapsed if elapsed else 0.0

    @property
    def cost_per_1k_tasks(self) -> float:
        """Coût d'un run complet du jeu de tâches, ramené à 1 000 exécutions."""
        if not self.samples:
            return 0.0
        total = sum(
            s.prompt_tokens / 1e6 * self.target.price_in + s.completion_tokens / 1e6 * self.target.price_out
            for s in self.samples
        )
        return total / len(self.samples) * 1000

    @property
    def errors(self) -> int:
        return sum(1 for s in self.samples if s.error)


def load_prices() -> dict[str, dict[str, float]]:
    if PRICES_FILE.exists():
        return json.loads(PRICES_FILE.read_text(encoding="utf-8"))
    return {}


def load_vision_tasks(path: Path = VISION_TASKS_FILE, captures: Path | None = None) -> list[dict[str, Any]]:
    """Tâches visuelles : chaque ligne porte une image du dossier captures, encodée ici."""
    import base64

    directory = Path(captures) if captures else CAPTURES_DIR
    tasks = load_tasks(path)
    for task in tasks:
        image = directory / str(task["image"])
        if not image.is_file():
            raise SystemExit(f"capture absente : {image}")
        mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        task["image_data_url"] = f"data:{mime};base64," + base64.b64encode(image.read_bytes()).decode()
    return tasks


def load_tasks(path: Path = TASKS_FILE) -> list[dict[str, Any]]:
    tasks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            tasks.append(json.loads(line))
    return tasks


def parse_target(spec: str, prices: dict[str, dict[str, float]]) -> Target:
    """`nom=url|modèle` ou `nom=url|modèle|clé`."""
    name, _, rest = spec.partition("=")
    parts = rest.split("|")
    if len(parts) < 2:
        raise SystemExit(f"cible invalide : {spec!r} (attendu nom=url|modèle)")
    base_url, model = parts[0].strip(), parts[1].strip()
    api_key = parts[2].strip() if len(parts) > 2 else ""
    price = prices.get(model, {})
    return Target(
        name=name.strip() or model,
        base_url=base_url.rstrip("/"),
        model=model,
        api_key=api_key,
        label="local" if _is_local(base_url) else "cloud",
        price_in=float(price.get("in", 0.0)),
        price_out=float(price.get("out", 0.0)),
    )


def targets_from_file(path: Path, prices: dict[str, dict[str, float]]) -> list[Target]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    targets = []
    for item in raw.get("targets", []):
        key = os.environ.get(item.get("api_key_env", ""), "") if item.get("api_key_env") else ""
        price = prices.get(item["model"], {})
        targets.append(
            Target(
                name=item.get("name") or item["model"],
                base_url=item["base_url"].rstrip("/"),
                model=item["model"],
                api_key=key,
                label=item.get("label") or ("local" if _is_local(item["base_url"]) else "cloud"),
                price_in=float(item.get("price_in", price.get("in", 0.0))),
                price_out=float(item.get("price_out", price.get("out", 0.0))),
            )
        )
    return targets


def _is_local(url: str) -> bool:
    return any(h in url for h in ("localhost", "127.0.0.1", "192.168.", "10.", "host.docker.internal", "ollama"))


def ask(
    target: Target, prompt: str, system: str, timeout: int, image_data_url: str | None = None
) -> tuple[str, int, int, float]:
    content: Any = prompt
    if image_data_url:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    payload = {
        "model": target.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "temperature": 0,
        "stream": False,
        "max_tokens": 512,
    }
    request = urllib.request.Request(
        f"{target.base_url}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {target.api_key}"} if target.api_key else {}),
        },
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = json.loads(response.read().decode())
    latency = time.perf_counter() - started
    text = body["choices"][0]["message"]["content"]
    usage = body.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or len(prompt.split()))
    completion_tokens = int(usage.get("completion_tokens") or len(text.split()))
    return text, prompt_tokens, completion_tokens, latency


def grade(task: dict[str, Any], reply: str) -> bool:
    """Notation déterministe : toutes les chaînes attendues doivent être présentes."""
    haystack = _normalise(reply)
    return all(_normalise(needle) in haystack for needle in task.get("expect", []))


def _normalise(text: str) -> str:
    """Casse, accents, espaces et séparateurs ignorés.

    Un modèle qui écrit « 860.900 » ou « 860 900 » a la bonne réponse : la notation
    ne doit pas le pénaliser. Les slashs et tirets des dates sont conservés.
    """
    strippe = "".join(
        ch for ch in unicodedata.normalize("NFKD", str(text).lower()) if not unicodedata.combining(ch)
    )
    for char in (" ", "\u202f", "\xa0", ".", ",", "'", "’", "\u00a0"):
        strippe = strippe.replace(char, "")
    return strippe.replace("€", "eur").replace("euros", "eur").strip()


def run_target(target: Target, tasks: list[dict[str, Any]], repeat: int, timeout: int, quiet: bool) -> TargetResult:
    result = TargetResult(target)
    system = (
        "Tu es un agent d'analyse. Réponds uniquement par la valeur demandée, sans phrase, "
        "sans balise Markdown, sans commentaire."
    )
    for round_index in range(repeat):
        for task in tasks:
            try:
                text, prompt_tokens, completion_tokens, latency = ask(
                    target, task["prompt"], system, timeout, task.get("image_data_url")
                )
                ok = grade(task, text)
                result.samples.append(
                    Sample(task["id"], ok, latency, prompt_tokens, completion_tokens, reply=text[:200])
                )
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                result.samples.append(Sample(task["id"], False, 0.0, 0, 0, error=str(exc)[:160]))
            if not quiet:
                sample = result.samples[-1]
                mark = "ok " if sample.ok else ("err" if sample.error else "ko ")
                print(f"  {mark} {sample.task_id:<26} {sample.latency_s:6.2f} s  {sample.completion_tokens:4d} tok")
    return result


def table(results: list[TargetResult]) -> str:
    head = (
        f"{'cible':<18} {'type':<6} {'réussite':>9} {'p50':>7} {'p95':>7} {'tok/s':>7} "
        f"{'€/1000':>9} {'erreurs':>8}"
    )
    lines = [head, "-" * len(head)]
    for r in results:
        cost = "0 (local)" if r.target.free else f"{r.cost_per_1k_tasks:,.2f} €".replace(",", " ")
        lines.append(
            f"{r.target.name:<18} {r.target.label:<6} {r.ok_rate:8.0f}% {r.p50:6.2f}s {r.p95:6.2f}s "
            f"{r.tokens_out_per_s:6.1f} {cost:>9} {r.errors:8d}"
        )
    return "\n".join(lines)


def markdown_report(results: list[TargetResult], tasks: list[dict[str, Any]], repeat: int) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    for r in results:
        cost = "0 € (local)" if r.target.free else f"{r.cost_per_1k_tasks:,.2f} €".replace(",", " ")
        rows.append(
            f"| {r.target.name} | {r.target.label} | `{r.target.model}` | {r.ok_rate:.0f} % | "
            f"{r.p50:.2f} s | {r.p95:.2f} s | {r.tokens_out_per_s:.1f} | {cost} |"
        )
    detail = []
    for r in results:
        for sample in r.samples:
            detail.append(
                f"| {r.target.name} | {sample.task_id} | {'ok' if sample.ok else 'ko'} | "
                f"{sample.latency_s:.2f} | {sample.prompt_tokens} | {sample.completion_tokens} |"
            )
    return f"""# Mesures, agent local vs cloud

Généré le {stamp} · {len(tasks)} tâches · {repeat} passe(s) · notation par correspondance exacte.

## Résultats

| Cible | Type | Modèle | Réussite | p50 | p95 | tokens/s | Coût / 1 000 tâches |
| --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(rows)}

## Méthode

- mêmes {len(tasks)} tâches, même prompt système, température 0, un appel par tâche ;
- notation **déterministe** : la réponse doit contenir toutes les chaînes attendues
  (`bench/tasks.jsonl`), pas d'appréciation humaine ;
- latence mesurée côté client (aller-retour complet), p50/p95 sur tous les échantillons ;
- coût = tokens réellement rapportés par l'endpoint × prix au million
  (`bench/prices.json`), ramené à 1 000 exécutions de la tâche.

## Ce que ces chiffres ne disent pas

- pas de mesure de qualité sur des tâches longues ou ambiguës : le jeu est volontairement
  vérifiable, donc conservateur ;
- les endpoints distants varient avec la charge réseau : refaire la mesure pour un chiffre
  défendable ;
- le coût « local » ne compte que l'électricité et le matériel, pas l'amortissement du GPU.

## Détail par tâche

| Cible | Tâche | Résultat | Latence (s) | Tokens in | Tokens out |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(detail)}
"""


def bar_svg(results: list[TargetResult], path: Path) -> None:
    width, height = 640, 300
    left, top, bottom = 60, 40, 50
    plot_w, plot_h = width - left - 30, height - top - bottom
    peak = max((r.p50 for r in results), default=1.0) or 1.0
    slot = plot_w / max(1, len(results))
    bar_w = min(90, slot * 0.55)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#12151c"/>',
        f'<text x="{left}" y="24" fill="#e8ecf4" font-family="monospace" font-size="14">Latence p50 par cible (s)</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{width - 20}" y2="{top + plot_h}" stroke="#39404f"/>',
    ]
    for index, r in enumerate(results):
        bar_h = (r.p50 / peak) * plot_h
        x = left + index * slot + (slot - bar_w) / 2
        y = top + plot_h - bar_h
        colour = "#3ecf8e" if r.target.label == "local" else "#5b8cff"
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{colour}" rx="3"/>')
        out.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" fill="#9aa6bd" font-family="monospace" '
            f'font-size="11" text-anchor="middle">{r.p50:.2f}s</text>'
        )
        out.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{top + plot_h + 18:.1f}" fill="#7c8698" font-family="monospace" '
            f'font-size="10" text-anchor="middle">{r.target.name[:14]}</text>'
        )
    out.append("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Banc de mesure agent local vs cloud")
    parser.add_argument("--target", action="append", default=[], help="nom=url|modèle[|clé]")
    parser.add_argument("--targets", help="fichier JSON de cibles (bench/targets.example.json)")
    parser.add_argument("--tasks", default=None, help="fichier de tâches (défaut selon la suite)")
    parser.add_argument("--suite", choices=["text", "vision"], default="text", help="jeu de tâches")
    parser.add_argument(
        "--captures", default=str(CAPTURES_DIR), help="dossier des images du banc vision"
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--out", default=str(REPORTS_DIR))
    args = parser.parse_args(argv)

    prices = load_prices()
    targets: list[Target] = []
    if args.targets:
        targets += targets_from_file(Path(args.targets), prices)
    targets += [parse_target(spec, prices) for spec in args.target]
    if not targets:
        parser.error("au moins une cible : --target ou --targets")

    if args.suite == "vision":
        tasks = load_vision_tasks(
            Path(args.tasks) if args.tasks else VISION_TASKS_FILE, Path(args.captures)
        )
    else:
        tasks = load_tasks(Path(args.tasks) if args.tasks else TASKS_FILE)
    print(f"▸ {len(tasks)} tâches · suite {args.suite} · {args.repeat} passe(s) · {len(targets)} cible(s)")
    results = []
    for target in targets:
        print(f"\n, {target.name} ({target.label}, {target.model}) → {target.base_url}")
        results.append(run_target(target, tasks, args.repeat, args.timeout, args.quiet))

    print("\n" + table(results))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_md = out_dir / f"mesures-{stamp}.md"
    report_json = out_dir / f"mesures-{stamp}.json"
    chart = out_dir / f"latence-{stamp}.svg"
    report_md.write_text(markdown_report(results, tasks, args.repeat), encoding="utf-8")
    bar_svg(results, chart)
    report_json.write_text(
        json.dumps(
            {
                "generated_at": stamp,
                "tasks": len(tasks),
                "repeat": args.repeat,
                "results": [
                    {
                        "target": r.target.name,
                        "model": r.target.model,
                        "label": r.target.label,
                        "base_url": r.target.base_url,
                        "ok_rate": round(r.ok_rate, 1),
                        "p50_s": round(r.p50, 3),
                        "p95_s": round(r.p95, 3),
                        "tokens_out_per_s": round(r.tokens_out_per_s, 1),
                        "cost_per_1k_tasks": round(r.cost_per_1k_tasks, 4),
                        "errors": r.errors,
                        "samples": [s.__dict__ for s in r.samples],
                    }
                    for r in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n▸ rapport  : {report_md}")
    print(f"▸ données  : {report_json}")
    print(f"▸ graphique: {chart}")
    return 0 if all(r.errors == 0 for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
