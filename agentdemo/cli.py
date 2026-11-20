"""Command line entry point.

  python -m agentdemo scenarios
  python -m agentdemo run --scenario cyber-brief
  python -m agentdemo run --scenario cyber-brief --live --model qwen2.5-coder:7b
  python -m agentdemo serve --port 8080
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from .agent import Agent
from .planners import OpenAICompatPlanner, ReplayPlanner
from .scenarios_loader import get_scenario, list_scenarios
from .tools import build_registry

DEFAULT_DATA_DIR = Path(os.environ.get("AGENTDEMO_DATA_DIR", "data"))


def _make_planner(scenario, live: bool, model: str | None, base_url: str | None):
    if live:
        stub_tools = build_registry(_NullSandbox(), [])
        return OpenAICompatPlanner(base_url=base_url, model=model, tools=stub_tools)
    return ReplayPlanner(scenario.cassette())


class _NullSandbox:
    """Only used to build the tool catalogue for the system prompt."""

    def __init__(self) -> None:
        self.root = Path(".")

    def resolve(self, relative: str) -> Path:
        return Path(relative)


def cmd_scenarios(_args: argparse.Namespace) -> int:
    for scenario in list_scenarios():
        print(f"{scenario.slug:<14} {scenario.title}")
        print(f"{'':14} {scenario.blurb}")
        print(f"{'':14} objectif : {scenario.objective[:120]}…")
        print()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    scenario = get_scenario(args.scenario)
    run_id = uuid.uuid4().hex[:10]
    root = Path(args.out or DEFAULT_DATA_DIR)
    workspace = root / "runs" / run_id / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    scenario.stage(workspace)

    planner = _make_planner(scenario, args.live, args.model, args.base_url)
    agent = Agent(
        planner=planner,
        workspace=workspace,
        runs_dir=root / "runs",
        max_steps=args.max_steps or scenario.max_steps,
    )

    print(f"▸ scénario  : {scenario.slug} ({scenario.title})")
    print(f"▸ planificateur : {getattr(planner, 'label', '?')}")
    print(f"▸ objectif  : {scenario.objective}")
    print(f"▸ espace    : {workspace}")
    print()

    def on_step(step) -> None:
        tool = step.tool or "final"
        mark = "✗" if step.error else "·"
        print(f"{mark} [{step.index:02d}] {tool:<16} {step.duration_ms:>4} ms  {step.thought[:96]}")
        if step.tool is None and step.observation:
            print(f"        ↳ {step.observation[:200]}")

    agent.on_step = on_step
    result = agent.run(scenario.objective, run_id=run_id)

    print()
    print(f"▸ statut    : {result.status}")
    print(f"▸ bilan     : {result.summary}")
    print(f"▸ livrables : {', '.join(result.artifacts) or '(aucun)'}")
    print(f"▸ journal   : {root / 'runs' / (run_id + '.json')}")
    return 0 if result.status == "done" else 1


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve  # imported lazily: CLI mode must not require sockets

    serve(host=args.host, port=args.port, data_dir=Path(args.out or DEFAULT_DATA_DIR))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentdemo", description="Agent Computer — demo agentique")
    parser.add_argument("--out", help="répertoire de travail (défaut : ./data)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scenarios", help="liste les scénarios").set_defaults(func=cmd_scenarios)

    run = sub.add_parser("run", help="exécute un scénario en ligne de commande")
    run.add_argument("--scenario", default="cyber-brief")
    run.add_argument("--live", action="store_true", help="utilise un modèle réellement (OpenAI-compatible)")
    run.add_argument("--model", help="nom du modèle en mode live")
    run.add_argument("--base-url", help="endpoint compatible OpenAI (défaut : http://localhost:11434/v1)")
    run.add_argument("--max-steps", type=int)
    run.set_defaults(func=cmd_run)

    serve = sub.add_parser("serve", help="lance l'interface web")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8080)
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
