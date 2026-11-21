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
from .sandbox import runner_for as _runner_for
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
    if not args.live and not scenario.has_cassette():
        print(
            f"le scénario « {args.scenario} » n'a pas de cassette : lance-le en mode réel "
            f"(--live --model ...) pour en produire une, ou enregistre la trace depuis l'interface",
            file=sys.stderr,
        )
        return 1
    run_id = uuid.uuid4().hex[:10]
    root = Path(args.out or DEFAULT_DATA_DIR)
    workspace = root / "runs" / run_id / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    scenario.stage(workspace)
    skills = SkillStore(root / "skills")  # persiste entre les runs, c'est le principe

    def approver(tool: str, args_: dict) -> bool:
        """Demande l'accord de l'opérateur avant une écriture ou une commande."""
        if tool == "run" and not getattr(args, "interactive", False):
            return True
        cible = args_.get("path") or args_.get("dst") or args_.get("command") or args_.get("uid") or ""
        print(f"\n  ⚠ {tool} sur {cible!r}")
        try:
            answer = input("    exécuter ? [o/N] ").strip().lower()
        except EOFError:
            answer = ""
        return answer in ("o", "oui", "y", "yes")

    confirm = None
    if getattr(args, "interactive", False) or getattr(args, "confirm_writes", False):
        confirm = approver

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
            network_config=scenario.network,
            runner=_runner_for(workspace, scenario),
            approver=confirm,
            scenario=scenario.slug,
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
    if not args.force:
        # l'utilisateur écrit dans le volume de données, pas dans le paquet installé
        from .scenarios_loader import create_scenario, user_scenarios_dir

        try:
            scenario = create_scenario(
                slug=slug,
                title=args.title or slug.replace("-", " ").capitalize(),
                objective=args.objective or "À décrire : l'objectif complet donné à l'agent.",
                blurb=args.blurb or "",
                tags=args.tag or [],
            )
        except (ValueError, OSError) as exc:
            print(f"refusé : {exc}", file=sys.stderr)
            return 1
        print(f"▸ scénario créé : {scenario.root}")
        print(f"  1. python3 -m agentdemo run --scenario {slug} --live --model <modèle>")
        print(f"  2. ou écris la cassette à la main dans {scenario.root / 'cassette.json'}")
        print(f"  3. dépose les données d'entrée dans {scenario.root / 'fixtures'}")
        print(f"  (racine des scénarios utilisateur : {user_scenarios_dir()})")
        return 0
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


def cmd_route(args: argparse.Namespace) -> int:
    """Affiche (ou force) la décision de routage pour un objectif donné."""
    from .routing import RoutingError, RoutingTable

    path = Path(args.out or DEFAULT_DATA_DIR) / "routing.json"
    try:
        table = RoutingTable.load(path)
        if args.override is not None:
            table.override = "" if args.override in ("", "none", "aucun") else args.override
            table.save(path)
            print(f"forçage manuel : {table.override or 'désactivé'}")
        if not args.objective:
            print(f"{len(table.targets)} cible(s), {len(table.rules)} règle(s), défaut : {table.default_target}")
            for rule in table.rules:
                where = f" {rule.value}" if rule.value else ""
                print(f"  - {rule.match}{where} → {rule.target} ({rule.note})")
            return 0
        decision = table.resolve(args.objective, args.scenario or "")
    except RoutingError as exc:
        print(f"erreur de politique : {exc}", file=sys.stderr)
        return 1
    print(f"objectif  : {args.objective}")
    print(f"scénario  : {args.scenario or '(aucun)'}")
    print(f"décision  : {decision.target.id} ({decision.target.model}, {decision.target.kind})")
    print(f"raison    : {decision.reason}")
    print(f"règle     : {decision.matched}")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Sert les outils de Vigie à un client MCP, en JSON-RPC sur stdio."""
    from .mcp_server import serve_stdio

    root = Path(args.out or DEFAULT_DATA_DIR)
    serve_stdio(root / "mcp-workspace", root)
    return 0


def cmd_scenario(args: argparse.Namespace) -> int:
    """Cycle de vie d'un scénario : lister, supprimer, en création voir `new`."""
    from .scenarios_loader import remove_scenario

    root = Path(args.out or DEFAULT_DATA_DIR)
    if args.action == "duplicate":
        from .scenarios_loader import duplicate_scenario

        try:
            copy = duplicate_scenario(args.name, args.to or f"{args.name}-copie")
        except (ValueError, KeyError) as exc:
            print(f"refusé : {exc}", file=sys.stderr)
            return 1
        print(f"▸ copie créée : {copy.slug} ({copy.root})")
        return 0
    if args.action != "remove":
        print("usage : agentdemo scenario remove|duplicate <nom>", file=sys.stderr)
        return 2
    try:
        preview = remove_scenario(args.name, root, force=args.force, dry_run=not args.yes)
    except (ValueError, KeyError) as exc:
        print(f"refusé : {exc}", file=sys.stderr)
        return 1
    print(f"▸ scénario : {preview['scenario']}{' (livré)' if preview['builtin'] else ''}")
    print(f"▸ dossier  : {preview['root']}")
    print(f"▸ runs     : {len(preview['runs'])} artefact(s)")
    for name in preview["runs"][:5]:
        print(f"    - {name}")
    print(f"▸ procédures rattachées : {', '.join(preview['skills']) or 'aucune'}")
    if not args.yes:
        print("\nRien n'a été supprimé. Relance avec --yes pour confirmer.")
        return 0
    print("\nSupprimé.")
    return 0


def cmd_scenario_show(args: argparse.Namespace) -> int:
    """Détail d'un scénario : ce que l'interface affiche, en texte."""
    from .scenarios_loader import scenario_detail

    try:
        detail = scenario_detail(args.name)
    except KeyError as exc:
        print(f"refusé : {exc}", file=sys.stderr)
        return 1
    print(f"▸ {detail['slug']} · {detail['title']}{' (livré)' if detail['builtin'] else ''}")
    print(f"  objectif   : {detail['objective']}")
    print(f"  étapes max : {detail['max_steps']} · cassette : {detail['steps']} étapes")
    print(f"  réseau     : {detail['network']}")
    print(f"  exec       : {detail['exec'] or 'désactivé'}")
    print(f"  entrées    : {detail['inputs'] or 'aucune'}")
    print(f"  fixtures   : {', '.join(detail['fixtures']) or 'aucune'}")
    print(f"  éditable   : {'oui' if detail['editable'] else 'non, à dupliquer'}")
    return 0


def cmd_scenario_edit(args: argparse.Namespace) -> int:
    """Modifie un scénario utilisateur : réseau, exécution, entrées, budget."""
    from .scenarios_loader import update_scenario

    payload: dict[str, object] = {}
    if args.title:
        payload["title"] = args.title
    if args.objective:
        payload["objective"] = args.objective
    if args.steps:
        payload["max_steps"] = args.steps
    if args.network:
        payload["network"] = {
            "mode": args.network,
            "hosts": [h.strip() for h in (args.hosts or "").split(",") if h.strip()],
        }
    if args.allow_exec:
        payload["exec"] = {"allow_unsandboxed": True, "reason": "déclaré en CLI"}
    if args.input_dir:
        payload["inputs"] = {"dir": args.input_dir, "feeds": []}
    try:
        updated = update_scenario(args.name, payload)
    except (ValueError, KeyError) as exc:
        print(f"refusé : {exc}", file=sys.stderr)
        return 1
    print(f"▸ {updated.slug} mis à jour : réseau {updated.network.get('mode')}, "
          f"{updated.max_steps} étapes max, entrées {updated.inputs or 'aucune'}")
    return 0


def cmd_mcp_servers(args: argparse.Namespace) -> int:
    """Liste, ajoute ou retire un serveur MCP dans les réglages."""
    from .settings_store import McpServer, Settings

    path = Path(args.out or DEFAULT_DATA_DIR) / "settings.json"
    settings = Settings.load(path)
    if args.action == "list":
        if not settings.mcp_servers:
            print("aucun serveur MCP configuré")
        for server in settings.mcp_servers:
            state = "actif" if server.enabled else "en pause"
            print(f"- {server.name} [{state}] {server.command} {' '.join(server.args)}".rstrip())
        return 0
    if args.action == "add":
        if not args.name or not args.command:
            print("usage : agentdemo mcp-servers add --name X --command python3 --args '-m,module'", file=sys.stderr)
            return 2
        settings.mcp_servers.append(
            McpServer(name=args.name, command=args.command,
                      args=[a.strip() for a in (args.args or "").split(",") if a.strip()],
                      description="ajouté en CLI", source="cli")
        )
    if args.action == "remove":
        before = len(settings.mcp_servers)
        settings.mcp_servers = [srv for srv in settings.mcp_servers if srv.name != args.name]
        if len(settings.mcp_servers) == before:
            print(f"serveur inconnu : {args.name}", file=sys.stderr)
            return 1
    try:
        settings.save(path)
    except ValueError as exc:
        print(f"refusé : {exc}", file=sys.stderr)
        return 1
    print(f"▸ {len(settings.mcp_servers)} serveur(s) MCP configuré(s)")
    return 0


def cmd_tool(args: argparse.Namespace) -> int:
    """Catalogue d'outils : lister, installer par manifeste vérifié, retirer."""
    from . import toolcatalog

    root = Path(args.out or DEFAULT_DATA_DIR)
    try:
        if args.action == "list":
            rows = toolcatalog.installed(root)
            if not rows:
                print("aucun outil installé")
            for row in rows:
                print(f"- {row['name']} {row['version']} : {row['description']} (sha256 {row['sha256'][:12]}…)")
            return 0
        if args.action == "install":
            result = toolcatalog.install(root, args.name, force=args.force, approved=args.yes)
            print(f"▸ {result['name']} {result['version']} installé dans {result['path']}")
            print(f"  empreinte vérifiée : {result['sha256'][:16]}…")
            return 0
        if args.action == "remove":
            result = toolcatalog.remove(root, args.name, approved=args.yes)
            print(f"▸ {result['removed']} retiré")
            return 0
    except toolcatalog.CatalogError as exc:
        print(f"refusé : {exc}", file=sys.stderr)
        return 1
    print("usage : agentdemo tool <list|install|remove> <nom> [--yes] [--force]", file=sys.stderr)
    return 2


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnostic d'installation : ce qui est prêt, ce qui manque, ce qui est optionnel."""
    from .doctor import doctor

    text, code = doctor(Path(args.out or DEFAULT_DATA_DIR), args.base_url, args.model)
    print(text)
    return code


def cmd_export(args: argparse.Namespace) -> int:
    """Archive un run : journal, livrables et une page de synthèse, dans un seul ZIP."""
    from .export import export_run, list_runs

    runs_dir = Path(args.out or DEFAULT_DATA_DIR) / "runs"
    run_id = args.run
    if not run_id:
        known = list_runs(runs_dir)
        if not known:
            print("aucun run à exporter, lance d'abord un scénario", file=sys.stderr)
            return 1
        run_id = known[0]
    try:
        exported = export_run(runs_dir, run_id, Path(args.file) if args.file else None)
    except FileNotFoundError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1
    print(f"run {exported.run_id} exporté : {exported.summary()}")
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

    mcp = sub.add_parser("mcp", help="sert les outils en MCP (JSON-RPC sur stdio)")
    mcp.add_argument("--out", help="dossier de données")
    mcp.set_defaults(func=cmd_mcp)

    mcp_servers = sub.add_parser("mcp-servers", help="serveurs MCP configurés")
    mcp_servers.add_argument("action", choices=["list", "add", "remove"])
    mcp_servers.add_argument("--name")
    mcp_servers.add_argument("--command")
    mcp_servers.add_argument("--args", help="arguments séparés par des virgules")
    mcp_servers.add_argument("--out", help="dossier de données")
    mcp_servers.set_defaults(func=cmd_mcp_servers)

    scenario_show = sub.add_parser("show", help="détail d'un scénario")
    scenario_show.add_argument("name")
    scenario_show.set_defaults(func=cmd_scenario_show)

    scenario_edit = sub.add_parser("edit", help="modifie un scénario utilisateur")
    scenario_edit.add_argument("name")
    scenario_edit.add_argument("--title")
    scenario_edit.add_argument("--objective")
    scenario_edit.add_argument("--steps", type=int)
    scenario_edit.add_argument("--network", choices=["deny", "allowlist", "open"])
    scenario_edit.add_argument("--hosts", help="domaines autorisés, séparés par des virgules")
    scenario_edit.add_argument("--allow-exec", action="store_true")
    scenario_edit.add_argument("--input-dir")
    scenario_edit.set_defaults(func=cmd_scenario_edit)

    scenario = sub.add_parser("scenario", help="cycle de vie d'un scénario")
    scenario.add_argument("action", choices=["remove", "duplicate"], help="action à effectuer")
    scenario.add_argument("name", help="slug du scénario")
    scenario.add_argument("--force", action="store_true", help="autorise un scénario livré")
    scenario.add_argument("--yes", action="store_true", help="confirme la suppression")
    scenario.add_argument("--to", help="slug de la copie (duplicate)")
    scenario.add_argument("--out", help="dossier de données")
    scenario.set_defaults(func=cmd_scenario)

    tool = sub.add_parser("tool", help="catalogue d'outils vérifiés")
    tool.add_argument("action", choices=["list", "install", "remove"])
    tool.add_argument("name", nargs="?", help="nom ou dossier du manifeste")
    tool.add_argument("--yes", action="store_true", help="accord explicite de l'opérateur")
    tool.add_argument("--force", action="store_true", help="remplace une installation existante")
    tool.add_argument("--out", help="dossier de données")
    tool.set_defaults(func=cmd_tool)

    route = sub.add_parser("route", help="décision de routage pour un objectif")
    route.add_argument("--objective", help="objectif à router (sinon, affiche la politique)")
    route.add_argument("--scenario", help="slug de scénario, utilisé par les règles de type scenario")
    route.add_argument("--override", help="force une cible ('none' pour désactiver le forçage)")
    route.set_defaults(func=cmd_route)

    doctor = sub.add_parser("doctor", help="vérifie que l'installation peut tourner")
    doctor.add_argument("--base-url", help="endpoint de modèle à tester (optionnel)")
    doctor.add_argument("--model", help="nom du modèle attendu (optionnel)")
    doctor.set_defaults(func=cmd_doctor)

    export = sub.add_parser("export", help="archive un run (journal et livrables)")
    export.add_argument("--run", help="identifiant du run (défaut : le plus récent)")
    export.add_argument("--file", help="chemin du ZIP à produire")
    export.set_defaults(func=cmd_export)

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
