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
from .scenarios_loader import SCENARIOS_DIR, Scenario, get_scenario, list_scenarios
from .skills import SkillStore
from .tools import build_registry
from .scenarios_loader import Scenario

DEFAULT_DATA_DIR = Path(os.environ.get("AGENTDEMO_DATA_DIR", "data"))


def _make_planner(
    scenario,
    live: bool,
    model: str | None,
    base_url: str | None,
    index: int = 0,
    api_key: str | None = None,
):
    if live:
        stub_tools = build_registry(_NullSandbox(), [])
        return OpenAICompatPlanner(
            base_url=base_url, model=model, api_key=api_key, tools=stub_tools
        )
    return ReplayPlanner(scenario.cassette(index))


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
        if len(scenario.pass_labels()) > 1:
            print(f"{'':14} passes   : {' / '.join(scenario.pass_labels())}")
        print()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    scenario = get_scenario(args.scenario)
    run_id = uuid.uuid4().hex[:10]
    root = Path(args.out or DEFAULT_DATA_DIR)
    workspace = root / "runs" / run_id / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    scenario.stage(workspace)
    skills = SkillStore(root / "skills")  # persiste entre les runs, c'est le principe

    print(f"▸ scénario  : {scenario.slug} ({scenario.title})")
    print(f"▸ objectif  : {scenario.objective}")
    print(f"▸ espace    : {workspace}")
    print()

    status = "done"
    recap = []
    for index, label in enumerate(scenario.pass_labels()):
        for change in scenario.apply_mutations(index, workspace):
            print(f"  (fixture modifiée avant la passe : {change})")
        planner = _make_planner(
            scenario, args.live, args.model, args.base_url, index, args.api_key
        )
        print(f"▸ {label or f'passe {index + 1}'} · planificateur {getattr(planner, 'label', '?')}")

        def on_step(step) -> None:
            tool = step.tool or "final"
            mark = "✗" if step.error else "·"
            print(f"  {mark} [{step.index:02d}] {tool:<16} {step.duration_ms:>4} ms  {step.thought[:90]}")

        agent = Agent(
            planner=planner,
            workspace=workspace,
            runs_dir=root / "runs",
            max_steps=args.max_steps or scenario.max_steps,
            on_step=on_step,
            skills=skills,
            children_dir=scenario.root / "children",
        )
        result = agent.run(scenario.objective, run_id=f"{run_id}-p{index + 1}")
        errors = sum(1 for s in result.steps if s.error)
        recap.append(f"{label or f'passe {index + 1}'} : {len(result.steps)} étapes, {errors} erreur(s), {result.status}")
        status = result.status
        print()

    print("▸ statut    :", status)
    for line in recap:
        print("▸", line)
    print(f"▸ bilan     : {result.summary}")
    print(f"▸ livrables : {', '.join(result.artifacts) or '(aucun)'}")
    print(f"▸ journal   : {root / 'runs' / (run_id + '-p1.json')}")
    return 0 if status == "done" else 1


def _tool_params(tool) -> tuple[list[str], list[str]]:
    """Depuis `fs_move(src, dst)` -> (['src','dst'], ['src','dst']) ; `?` = optionnel."""
    inside = tool.signature.split("(", 1)[1].rstrip(")")
    required, optional = [], []
    for raw in [p.strip() for p in inside.split(",") if p.strip()]:
        name = raw.split(":")[0].strip().replace("[]", "")
        if name.endswith("?"):
            optional.append(name.rstrip("?"))
        elif not name.startswith("*"):
            required.append(name)
        else:
            optional.append(name.lstrip("*"))
    return required, optional


def cmd_validate(args: argparse.Namespace) -> int:
    """Vérifie chaque cassette contre les outils réels : nom d'outil et arguments."""
    from .tools import Sandbox

    sandbox = Sandbox(Path(args.out or DEFAULT_DATA_DIR) / "_validate")
    tools = build_registry(sandbox, [])
    problems = 0
    for scenario in list_scenarios():
        if args.slug and scenario.slug != args.slug:
            continue
        errors: list[str] = []
        labels = scenario.pass_labels()
        for index in range(len(labels)):
            steps = scenario.cassette(index)
            if not steps:
                errors.append(f"passe {index + 1} : cassette vide")
                continue
            if not any(step.get("final") for step in steps):
                errors.append(f"passe {index + 1} : aucune étape 'final'")
            for number, step in enumerate(steps, 1):
                tool_name = step.get("tool")
                if not tool_name:
                    continue
                if tool_name not in tools:
                    errors.append(f"passe {index + 1} étape {number} : outil inconnu « {tool_name} »")
                    continue
                required, optional = _tool_params(tools[tool_name])
                given = set((step.get("args") or {}).keys())
                missing = [name for name in required if name not in given]
                extra = [name for name in given if name not in required + optional]
                if missing:
                    errors.append(
                        f"passe {index + 1} étape {number} : {tool_name} attend {missing}"
                    )
                if extra:
                    errors.append(
                        f"passe {index + 1} étape {number} : argument(s) inconnu(s) {extra} "
                        f"pour {tool_name}, attendu : {tools[tool_name].signature}"
                    )
        status = "ok" if not errors else "ko"
        print(f"[{status}] {scenario.slug} ({len(labels)} passe(s))")
        for error in errors:
            print(f"       - {error}")
        problems += len(errors)
    print()
    if problems:
        print(f"{problems} problème(s) à corriger avant de pousser")
        return 1
    print("toutes les cassettes sont cohérentes avec les outils")
    return 0


SCENARIO_TEMPLATE = {
    "slug": "",
    "title": "",
    "blurb": "",
    "objective": "",
    "max_steps": 10,
    "tags": [],
}

CASSETTE_TEMPLATE = [
    {
        "thought": "Je commence par inventorier ce que j'ai sous la main.",
        "tool": "fs_list",
        "args": {"path": "."},
    },
    {
        "thought": "À remplacer : les étapes réelles du raisonnement, une action par entrée.",
        "tool": "fs_read",
        "args": {"path": "exemple.txt"},
    },
    {"thought": "Livrable écrit et vérifié.", "final": "Objectif atteint."},
]


def cmd_new(args: argparse.Namespace) -> int:
    """Échafaude un scénario : dossier, scenario.json, cassette, fixtures."""
    slug = args.slug
    folder = SCENARIOS_DIR / slug
    if folder.exists() and not args.force:
        print(f"le scénario « {slug} » existe déjà ({folder})", file=sys.stderr)
        return 1
    (folder / "fixtures").mkdir(parents=True, exist_ok=True)
    meta = dict(SCENARIO_TEMPLATE)
    meta.update(
        slug=slug,
        title=args.title or slug.replace("-", " ").capitalize(),
        blurb=args.blurb or "À décrire en une phrase : ce que l'agent doit produire.",
        objective=args.objective or "À décrire : l'objectif complet donné à l'agent, avec le nom du livrable attendu.",
        tags=args.tag or [],
    )
    (folder / "scenario.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "cassette.json").write_text(
        json.dumps(CASSETTE_TEMPLATE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (folder / "fixtures" / "exemple.txt").write_text(
        "Remplace ce fichier par les données d'entrée du scénario (synthétiques, jamais réelles).\n",
        encoding="utf-8",
    )
    print(f"▸ scénario créé : {folder}")
    print("  1. décris l'objectif dans scenario.json")
    print("  2. déroule les étapes dans cassette.json (une action par entrée)")
    print("  3. dépose les données d'entrée dans fixtures/")
    print(f"  4. python3 -m agentdemo validate --slug {slug}")
    print(f"  5. python3 -m agentdemo run --scenario {slug}")
    return 0


def cmd_fit(args: argparse.Namespace) -> int:
    """Dimensionnement : ce qui tient dans une carte pour un contexte donné."""
    from .fit import table

    print(table(args.vram, args.context))
    print()
    print("estimation de dimensionnement (poids + cache d'attention + marge runtime), pas une mesure.")
    return 0


def cmd_maintain(args: argparse.Namespace) -> int:
    """Entretien automatique : réparer, arbitrer, retirer. Conçu pour tourner en tâche de fond."""
    from .maintenance import Maintainer

    root = Path(args.out or DEFAULT_DATA_DIR)
    store = SkillStore(root / "skills")
    runs = sorted((root / "runs").glob("*/workspace"), key=lambda p: p.stat().st_mtime, reverse=True)
    sandbox = runs[0] if runs else root / "runs" / "maintenance-sandbox"
    maintainer = Maintainer(store, sandbox, root / "maintenance.jsonl")

    def show(report) -> None:
        stamp = report.started_at
        if not report.changed:
            print(f"[{stamp}] rien à faire ({report.scanned} procédures)")
            return
        print(f"[{stamp}] {report.scanned} procédures")
        for item in report.repaired:
            print(f"  réparée    : {item['procedure']} ({item['de']} -> {item['vers']})")
        for item in report.superseded:
            print(f"  arbitrées  : {item['topic']} : {item['winner']} garde la main, {item['loser']} passe superseded ({item['reason']})")
        for name in report.retired:
            print(f"  retirée    : {name}")

    if args.once or not args.interval:
        show(maintainer.run_once())
        return 0
    print(f"entretien toutes les {args.interval}s, Ctrl+C pour arrêter")
    try:
        maintainer.loop(args.interval, on_report=show)
    except KeyboardInterrupt:
        print("arrêt")
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    """Registre des procédures apprises : confiance, statut, mise à la retraite."""
    store = SkillStore(Path(args.out or DEFAULT_DATA_DIR) / "skills")
    if args.prune:
        retired = store.prune()
        print(f"{len(retired)} procédure(s) mise(s) à la retraite : {', '.join(retired) or 'aucune'}")
    if args.resolve:
        decisions = store.resolve_conflicts(args.resolve if isinstance(args.resolve, str) else None)
        for item in decisions:
            print(
                f"conflit sur « {item['topic']} » : {item['winner']} garde la main "
                f"({item['winner_confidence']} % contre {item['loser_confidence']} %), "
                f"{item['loser']} passe superseded"
            )
        if not decisions:
            print("aucun conflit de procédures détecté")
    rows = store.ledger()
    if not rows:
        print("aucune procédure enregistrée")
        return 0
    print(f"{'procédure':<24} {'statut':<8} {'succès':>7} {'usages':>7} {'confiance':>10}  contrat")
    print("-" * 84)
    for row in rows:
        print(
            f"{row['name']:<24} {row['status']:<8} {row['success']:>7} {row['uses']:>7} "
            f"{str(row['confidence']) + ' %':>10}  {row['check'] or '-'}"
        )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve  # imported lazily: CLI mode must not require sockets

    serve(host=args.host, port=args.port, data_dir=Path(args.out or DEFAULT_DATA_DIR))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentdemo", description="Agent Computer, demo agentique")
    parser.add_argument("--out", help="répertoire de travail (défaut : ./data)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scenarios", help="liste les scénarios").set_defaults(func=cmd_scenarios)

    run = sub.add_parser("run", help="exécute un scénario en ligne de commande")
    run.add_argument("--scenario", default="cyber-brief")
    run.add_argument("--live", action="store_true", help="utilise un modèle réellement (OpenAI-compatible)")
    run.add_argument("--model", help="nom du modèle en mode live")
    run.add_argument(
        "--base-url",
        help="endpoint compatible OpenAI, par exemple http://MON-IP:1234/v1 pour LM Studio "
        "(défaut : AGENTDEMO_LLM_BASE_URL ou http://localhost:11434/v1)",
    )
    run.add_argument("--api-key", help="clé API si l'endpoint en exige une (ou AGENTDEMO_LLM_API_KEY)")
    run.add_argument("--max-steps", type=int)
    run.set_defaults(func=cmd_run)

    validate = sub.add_parser("validate", help="vérifie les cassettes contre les outils réels")
    validate.add_argument("--slug", help="un seul scénario")
    validate.set_defaults(func=cmd_validate)

    new = sub.add_parser("new", help="échafaude un nouveau scénario")
    new.add_argument("--slug", required=True)
    new.add_argument("--title")
    new.add_argument("--blurb")
    new.add_argument("--objective")
    new.add_argument("--tag", action="append")
    new.add_argument("--force", action="store_true")
    new.set_defaults(func=cmd_new)

    fit = sub.add_parser("fit", help="quels modèles tiennent dans une carte")
    fit.add_argument("--vram", type=float, default=32.0, help="mémoire vidéo de la carte, en Go")
    fit.add_argument("--context", type=int, default=32768, help="contexte visé, en tokens")
    fit.set_defaults(func=cmd_fit)

    maintain = sub.add_parser("maintain", help="entretien automatique des procédures")
    maintain.add_argument("--once", action="store_true", help="une seule passe")
    maintain.add_argument("--interval", type=int, default=0, help="boucle toutes les N secondes")
    maintain.set_defaults(func=cmd_maintain)

    skills = sub.add_parser("skills", help="registre des procédures apprises")
    skills.add_argument("--prune", action="store_true", help="met à la retraite ce qui est périmé")
    skills.add_argument("--resolve", nargs="?", const=True, default=None, metavar="SUJET",
                        help="arbitre des procédures contradictoires, éventuellement sur un seul sujet")
    skills.set_defaults(func=cmd_skills)

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
