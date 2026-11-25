"""La veille du matin, exécutée pour de vrai et versionnée.

Ce script n'est pas une démonstration : c'est ce qui tourne chez moi. Il lance le scénario
`cyber-brief-live` sur les trois sources réelles, puis écrit le résultat dans
`docs/runs/<AAAAMMJJ>-veille/` :

    briefing.md      le livrable, tel que l'agent l'a écrit
    journal.jsonl    une ligne par étape, horodatée
    state.json       l'état de reprise, pour prouver que le run est reprenable
    meta.json        modèle, durée, statut, sources lues, échecs

et ajoute une ligne à `docs/production/journal.md`, **qu'il réussisse ou non**. Un jour sans run reste
visible avec le statut `absent` : c'est cette honnêteté qui rend la série crédible.

    python3 docs/production/veille.py --once
    python3 docs/production/veille.py --loop --interval 24
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
RUNS = REPO / "docs" / "runs"
JOURNAL = REPO / "docs" / "production" / "journal.md"
DATA = Path(os.environ.get("AGENTDEMO_DATA_DIR") or REPO / "data")

sys.path.insert(0, str(REPO))

from agentdemo.agent import Agent  # noqa: E402
from agentdemo.planners import OpenAICompatPlanner  # noqa: E402
from agentdemo.scenarios_loader import get_scenario  # noqa: E402
from agentdemo.settings_store import Settings  # noqa: E402
from agentdemo.skills import SkillStore  # noqa: E402
from agentdemo.tools import Sandbox, build_registry  # noqa: E402


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def target_dir(stamp: str) -> Path:
    """Un run relancé le même jour ne crée pas une deuxième ligne : suffixe -2, -3."""
    base = RUNS / f"{stamp}-veille"
    if not base.exists():
        return base
    index = 2
    while (RUNS / f"{stamp}-veille-{index}").exists():
        index += 1
    return RUNS / f"{stamp}-veille-{index}"


def append_journal(line: dict) -> None:
    """Le tableau du journal : une ligne par run, échecs compris."""
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "| Date | Statut | Durée | Étapes | Livrable | Modèle |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
    )
    if not JOURNAL.exists():
        JOURNAL.write_text("# Journal de la veille\n\n" + header, encoding="utf-8")
    text = JOURNAL.read_text(encoding="utf-8")
    if header not in text:
        text += "\n" + header
    entry = (
        f"| {line['date']} | {line['status']} | {line['duration']} | {line['steps']} | "
        f"{line['deliverable']} | {line['model']} |\n"
    )
    JOURNAL.write_text(text.rstrip("\n") + "\n" + entry, encoding="utf-8")


def run_once(base_url: str, model: str, api_key: str, timeout: int) -> dict:
    scenario = get_scenario("cyber-brief-live")
    stamp = today()
    directory = target_dir(stamp)
    workspace = directory / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    settings = Settings.load(DATA / "settings.json")
    skills = SkillStore(DATA / "skills")
    runner = None
    sandbox = Sandbox(workspace)
    tools = build_registry(sandbox, [], DATA, runner, settings=settings)
    planner = OpenAICompatPlanner(
        base_url=base_url,
        model=model,
        api_key=api_key,
        tools=tools,
        timeout=timeout,
    )
    started = time.time()
    result = Agent(
        planner=planner,
        workspace=workspace,
        runs_dir=directory / "runs",
        max_steps=scenario.max_steps,
        skills=skills,
        settings=settings,
        network_config=scenario.network,
        runner=runner,
        scenario=scenario.slug,
        save_state=True,
    ).run(scenario.objective, run_id=f"{stamp}-veille")
    elapsed = time.time() - started

    briefing = workspace / "briefing.md"
    if briefing.exists():
        shutil.copy2(briefing, directory / "briefing.md")
    with (directory / "journal.jsonl").open("w", encoding="utf-8") as handle:
        for step in result.steps:
            handle.write(
                json.dumps(
                    {
                        "index": step.index,
                        "tool": step.tool,
                        "error": bool(step.error),
                        "duration_ms": step.duration_ms,
                        "thought": step.thought[:200],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    state_source = directory / "runs" / f"{stamp}-veille" / "state.json"
    if state_source.exists():
        shutil.copy2(state_source, directory / "state.json")

    items = 0
    if briefing.exists():
        items = sum(1 for line in briefing.read_text(encoding="utf-8").splitlines() if line.startswith(("## ", "### ")))
    status = result.status
    if status == "done" and (not briefing.exists() or items == 0):
        # la règle du document : un briefing sans source n'est pas un livrable, il ne compte pas
        status = "vide"
    meta = {
        "date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}",
        "status": status,
        "duration_s": round(elapsed, 1),
        "steps": len(result.steps),
        "errors": sum(1 for s in result.steps if s.error),
        "model": model,
        "base_url": base_url,
        "items": items,
        "artifacts": list(result.artifacts),
        "summary": result.summary[:400],
    }
    (directory / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_journal(
        {
            "date": meta["date"],
            "status": meta["status"],
            "duration": f"{int(elapsed // 60)} min {int(elapsed % 60):02d}",
            "steps": str(meta["steps"]),
            "deliverable": f"briefing.md, {items} items" if status == "done" else "aucun",
            "model": model,
        }
    )
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description="veille quotidienne versionnée")
    parser.add_argument("--once", action="store_true", help="un run, maintenant")
    parser.add_argument("--loop", action="store_true", help="un run toutes les --interval heures")
    parser.add_argument("--interval", type=float, default=24.0)
    parser.add_argument("--base-url", default=os.environ.get("AGENTDEMO_LLM_BASE_URL", "http://127.0.0.1:1234/v1"))
    parser.add_argument("--model", default=os.environ.get("AGENTDEMO_LLM_MODEL", "qwen/qwen3-vl-8b"))
    parser.add_argument("--api-key", default=os.environ.get("AGENTDEMO_LLM_API_KEY", ""))
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not (args.once or args.loop):
        parser.error("choisis --once ou --loop")

    while True:
        meta = run_once(args.base_url, args.model, args.api_key, args.timeout)
        print(json.dumps(meta, ensure_ascii=False))
        if args.once:
            return 0 if meta["status"] == "done" else 1
        time.sleep(max(60.0, args.interval * 3600))


if __name__ == "__main__":
    raise SystemExit(main())
