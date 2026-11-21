"""Exécute un scénario avec un vrai modèle et versionne la trace dans `docs/runs/`.

Le but n'est pas de produire une jolie capture : c'est de laisser sur le disque ce qui s'est
réellement passé, y compris quand ça se passe mal. Trois fichiers par run :

* `journal.json` : chaque étape, arguments, observation, durée, erreurs ;
* `transcript.md` : la même chose en lisible, pour un humain pressé ;
* `meta.json` : modèle, durée totale, étapes, erreurs, politique réseau, niveau d'isolation.

    python3 bench/run_real.py --scenario cyber-brief --model qwen2.5-coder-7b-instruct \
        --base-url http://192.168.1.153:1234/v1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentdemo.agent import Agent  # noqa: E402
from agentdemo.planners import OpenAICompatPlanner  # noqa: E402
from agentdemo.sandbox import isolation_level, runner_for as _runner_for  # noqa: E402
from agentdemo.scenarios_loader import get_scenario  # noqa: E402
from agentdemo.skills import SkillStore  # noqa: E402

DATA_DIR = Path(os.environ.get("AGENTDEMO_DATA_DIR", "/data"))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def transcript(run: dict) -> str:
    lines = [
        f"# Run réel, {run['scenario']} · {run['planner']}",
        "",
        f"- objectif : {run['objective']}",
        f"- statut : **{run['status']}** · {len(run['steps'])} étapes · "
        f"{run['duration_s']} s · {sum(1 for s in run['steps'] if s['error'])} erreur(s)",
        f"- réseau : {run['network'].get('network_mode')} · isolation : {run['isolation']}",
        "",
        "| # | outil | durée | erreur | pensée |",
        "| --- | --- | --- | --- | --- |",
    ]
    for step in run["steps"]:
        thought = str(step["thought"]).replace("|", "\\|")[:160]
        lines.append(
            f"| {step['index']} | `{step['tool'] or 'final'}` | {step['duration_ms']} ms | "
            f"{'oui' if step['error'] else 'non'} | {thought} |"
        )
    lines += ["", "## Observations", ""]
    for step in run["steps"]:
        lines += [f"### {step['index']}. {step['tool'] or 'final'}", "", "```", str(step["observation"])[:1500], "```", ""]
    if run.get("events"):
        lines += ["## Événements", "", "```json", json.dumps(run["events"], ensure_ascii=False, indent=1), "```", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="run réel versionné")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://192.168.1.153:1234/v1")
    parser.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY", ""))
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "docs" / "runs"))
    parser.add_argument("--data", default=str(DATA_DIR))
    args = parser.parse_args()

    scenario = get_scenario(args.scenario)
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}"
    data_dir = Path(args.data)
    workspace = data_dir / "runs" / f"real-{run_id}" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    scenario.stage(workspace)

    planner = OpenAICompatPlanner(base_url=args.base_url, model=args.model, api_key=args.api_key)
    agent = Agent(
        planner=planner,
        workspace=workspace,
        runs_dir=data_dir / "runs",
        max_steps=scenario.max_steps,
        skills=SkillStore(data_dir / "skills"),
        children_dir=scenario.root / "children",
        network_config=scenario.network,
        runner=_runner_for(workspace, scenario),
        scenario=scenario.slug,
    )
    print(f"▸ {scenario.slug} · {args.model} · {args.base_url}", flush=True)
    result = agent.run(scenario.objective, run_id=f"real-{run_id}")
    payload = result.as_dict()
    payload["isolation"] = isolation_level()
    payload["artifacts_list"] = result.artifacts

    directory = Path(args.out) / f"{time.strftime('%Y%m%d')}-{slug(scenario.slug)}-{slug(args.model)}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "journal.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "transcript.md").write_text(transcript(payload), encoding="utf-8")
    meta = {
        "scenario": scenario.slug,
        "model": args.model,
        "endpoint_host": args.base_url.split("//")[-1].split("/")[0],
        "date": payload["started_at"],
        "status": payload["status"],
        "steps": len(payload["steps"]),
        "errors": sum(1 for s in payload["steps"] if s["error"]),
        "duration_s": payload["duration_s"],
        "network": payload["network"],
        "isolation": payload["isolation"],
        "artifacts": result.artifacts,
    }
    (directory / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    # les livrables restent lisibles à côté de la trace, pas seulement dans le bac à sable
    from shutil import copy2

    for name in result.artifacts:
        source = workspace / name
        if source.is_file():
            copy2(source, directory / Path(name).name)
    print(f"▸ statut {payload['status']} · {len(payload['steps'])} étapes · {payload['duration_s']} s")
    print(f"▸ trace : {directory}")
    return 0 if payload["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
