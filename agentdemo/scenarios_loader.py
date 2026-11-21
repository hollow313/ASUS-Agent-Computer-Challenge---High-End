"""Scenario loading: metadata, recorded decision trace, fixture files."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .skills import SkillStore

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


OVERRIDE_FIELDS = ("title", "blurb", "objective", "tags", "max_steps", "network", "exec", "inputs")


def overrides_dir() -> Path:
    """Surcharges des scénarios livrés : le dossier de données, jamais l'image."""
    base = Path(os.environ.get("AGENTDEMO_DATA_DIR") or "./data")
    path = base / "scenario-overrides"
    path.mkdir(parents=True, exist_ok=True)
    return path


def override_path(slug: str) -> Path:
    return overrides_dir() / f"{slug}.json"


def user_scenarios_dir() -> Path:
    """Scénarios créés par l'utilisateur : dans le volume de données, jamais dans l'image."""
    return Path(os.environ.get("AGENTDEMO_DATA_DIR", "./data")) / "scenarios"


def scenario_dirs() -> list[Path]:
    """Les scénarios livrés d'abord, puis ceux de l'utilisateur."""
    dirs = [Path(p) for p in (SCENARIOS_DIR, user_scenarios_dir())]
    return [d for d in dirs if d.is_dir()]


@dataclass
class Scenario:
    slug: str
    title: str
    blurb: str
    objective: str
    max_steps: int
    tags: list[str]
    root: Path
    passes: list[dict[str, Any]]
    network: dict[str, Any] = field(default_factory=lambda: {"mode": "deny"})
    exec_config: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    overridden: bool = False

    @property
    def builtin(self) -> bool:
        return str(self.root).startswith(str(SCENARIOS_DIR))

    def exec_policy(self) -> dict[str, Any]:
        return dict(self.exec_config or {})

    def cassette(self, index: int = 0) -> list[dict[str, Any]]:
        """Recorded trace of pass ``index`` (a scenario can be replayed twice to
        show what the agent learned between two runs)."""
        passes = self.passes or [{"label": "", "cassette": "cassette.json"}]
        name = passes[min(index, len(passes) - 1)].get("cassette", "cassette.json")
        path = self.root / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def pass_labels(self) -> list[str]:
        return [p.get("label", "") for p in (self.passes or [{"label": ""}])]

    def apply_mutations(self, index: int, workspace: Path) -> list[str]:
        """Applique les modifications prévues avant une passe (renommage, déplacement).

        Sert à démontrer qu'une procédure peut devenir fausse : le fichier sur lequel elle
        s'appuie est renommé entre deux passes, le contrat de vérification casse.
        """
        passes = self.passes or [{"label": ""}]
        entry = passes[min(index, len(passes) - 1)]
        applied = []
        for move in entry.get("mutate", {}).get("move", []):
            source, dest = workspace / move[0], workspace / move[1]
            if source.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                source.replace(dest)
                applied.append(f"{move[0]} -> {move[1]}")
        return applied

    def stage_inputs(self, workspace: Path) -> list[str]:
        """Copie le dossier d'entrée déclaré par le scénario dans `inputs/`."""
        directory = str(self.inputs.get("dir") or "").strip()
        if not directory:
            return []
        source = Path(directory)
        if not source.is_dir():
            return []
        target = workspace / "inputs"
        target.mkdir(parents=True, exist_ok=True)
        copied = []
        for item in sorted(source.rglob("*")):
            if item.is_file():
                relative = item.relative_to(source)
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)
                copied.append(f"inputs/{relative}")
        return copied

    def stage(self, workspace: Path) -> None:
        """Copy the scenario fixtures into the run workspace."""
        fixtures = self.root / "fixtures"
        if not fixtures.exists():
            return
        for item in fixtures.iterdir():
            destination = workspace / item.name
            if item.is_dir():
                shutil.copytree(item, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(item, destination)

    def has_cassette(self) -> bool:
        passes = self.passes or [{"label": "", "cassette": "cassette.json"}]
        name = passes[0].get("cassette", "cassette.json")
        return (self.root / name).exists() and bool(self.cassette())

    def as_summary(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "blurb": self.blurb,
            "objective": self.objective,
            "tags": self.tags,
            "steps": len(self.cassette()),
            "max_steps": self.max_steps,
            "passes": self.pass_labels(),
            "has_cassette": self.has_cassette(),
            "network": self.network,
            "exec": self.exec_config,
            "inputs": self.inputs,
            "builtin": self.builtin,
            "overridden": self.overridden,
            "user": str(self.root).startswith(str(user_scenarios_dir())),
        }


def list_scenarios(dirs: list[Path] | None = None) -> list[Scenario]:
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for base in (dirs or scenario_dirs()):
        if not Path(base).is_dir():
            continue
        for folder in sorted(Path(base).iterdir()):
            meta_file = folder / "scenario.json"
            if not (folder.is_dir() and meta_file.exists()):
                continue
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            slug_value = str(meta.get("slug") or folder.name)
            if slug_value in seen:
                continue
            seen.add(slug_value)
            overridden = False
            override = override_path(slug_value)
            if override.is_file():
                try:
                    local = json.loads(override.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    local = {}
                # la surcharge ne touche que les champs d'édition, jamais le dossier ni la cassette
                meta.update({key: value for key, value in local.items() if key in OVERRIDE_FIELDS})
                overridden = bool(local)
            scenarios.append(
                Scenario(
                    slug=slug_value,
                    title=str(meta.get("title") or slug_value),
                    blurb=str(meta.get("blurb") or ""),
                    objective=str(meta.get("objective") or ""),
                    max_steps=int(meta.get("max_steps") or 10),
                    tags=list(meta.get("tags") or []),
                    root=folder,
                    passes=list(meta.get("passes") or [{"label": "", "cassette": "cassette.json"}]),
                    network=dict(meta.get("network") or {"mode": "deny"}),
                    exec_config=dict(meta.get("exec") or {}),
                    inputs=dict(meta.get("inputs") or {}),
                    overridden=overridden,
                )
            )
    return scenarios


def get_scenario(slug: str, dirs: list[Path] | None = None) -> Scenario:
    for scenario in list_scenarios(dirs):
        if scenario.slug == slug:
            return scenario
    raise KeyError(f"scénario inconnu : {slug}")


def remove_scenario(
    slug: str, data_dir: Path, *, force: bool = False, dry_run: bool = False
) -> dict[str, Any]:
    """Supprime un scénario utilisateur, ses runs et ses procédures rattachées.

    Les cinq scénarios livrés sont marqués `builtin` et refusent la suppression sans `force`.
    Rien ne sort de `data/` : les chemins sont résolus et vérifiés avant toute suppression.
    """
    scenario = get_scenario(slug)
    builtin = str(scenario.root).startswith(str(SCENARIOS_DIR))
    if builtin and not force:
        raise ValueError(
            f"« {slug} » est un scénario livré : suppression refusée sans --force"
        )
    data_dir = Path(data_dir).resolve()
    runs_dir = (data_dir / "runs").resolve()
    artifacts: list[str] = []
    for journal in sorted(runs_dir.glob("*.json")):
        try:
            payload = json.loads(journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("scenario") != slug:
            continue
        artifacts.append(journal.name)
        workspace = runs_dir / journal.stem.split("-p")[0] / "workspace"
        if workspace.is_dir() and workspace.resolve().is_relative_to(runs_dir):
            artifacts.append(str(workspace.relative_to(data_dir)))
    skills = SkillStore(data_dir / "skills")
    attached = [row["name"] for row in skills.ledger() if row.get("topic") == slug]
    summary = {
        "scenario": slug,
        "builtin": builtin,
        "root": str(scenario.root),
        "runs": artifacts,
        "skills": attached,
    }
    if dry_run:
        return summary
    if not str(scenario.root).startswith(str(user_scenarios_dir().resolve())) and not force:
        raise ValueError("ce scénario n'est pas dans le dossier utilisateur : suppression refusée")
    import shutil

    shutil.rmtree(scenario.root)
    for name in artifacts:
        target = (data_dir / name).resolve()
        if not target.is_relative_to(data_dir):
            continue
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()
    retired = data_dir / "skills" / "retired"
    retired.mkdir(parents=True, exist_ok=True)
    for name in attached:
        source = data_dir / "skills" / f"{name}.md"
        if source.exists() and source.resolve().is_relative_to(data_dir):
            source.replace(retired / source.name)
    log = data_dir / "removals.jsonl"
    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "event": "scenario_removed",
                    "name": slug,
                    "artifacts": artifacts,
                    "skills": attached,
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return summary


def create_scenario(
    slug: str,
    title: str,
    objective: str,
    blurb: str = "",
    tags: list[str] | None = None,
    max_steps: int = 10,
    passes: list[dict[str, Any]] | None = None,
    network: dict[str, Any] | None = None,
    exec_config: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> Scenario:
    """Crée un scénario utilisateur, sans cassette : il se lance en mode réel, puis s'enregistre."""
    slug = str(slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise ValueError("slug invalide : lettres minuscules, chiffres et tirets, 2 à 41 caractères")
    if not str(title).strip() or not str(objective).strip():
        raise ValueError("un titre et un objectif sont nécessaires")
    folder = user_scenarios_dir() / slug
    if folder.exists():
        raise ValueError(f"le scénario « {slug} » existe déjà")
    (folder / "fixtures").mkdir(parents=True, exist_ok=True)
    meta = {
        "slug": slug,
        "title": str(title).strip(),
        "blurb": str(blurb).strip() or "Scénario créé depuis l'interface.",
        "objective": str(objective).strip(),
        "max_steps": max(2, min(int(max_steps or 10), 24)),
        "tags": [str(t) for t in (tags or [])],
        "passes": passes or [{"label": "", "cassette": "cassette.json"}],
    }
    mode = str((network or {}).get("mode") or "deny")
    hosts = [str(h).strip().lower() for h in ((network or {}).get("hosts") or []) if str(h).strip()]
    if mode not in ("deny", "allowlist", "open"):
        raise ValueError(f"mode réseau inconnu : {mode}")
    if mode == "allowlist" and not hosts:
        raise ValueError("allowlist sans hôte : ajoute au moins un domaine")
    meta["network"] = {"mode": mode, "hosts": hosts}
    meta["exec"] = {
        "allow_unsandboxed": bool((exec_config or {}).get("allow_unsandboxed")),
        "reason": str((exec_config or {}).get("reason") or ""),
    }
    meta["inputs"] = {
        "dir": str((inputs or {}).get("dir") or "").strip(),
        "feeds": [str(f).strip() for f in ((inputs or {}).get("feeds") or []) if str(f).strip()],
    }
    (folder / "scenario.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scenario = get_scenario(slug)
    return scenario


def record_cassette(scenario: Scenario, steps: list[dict[str, Any]], summary: str = "") -> Path:
    """Transforme la trace réelle d'un run en cassette rejouable.

    On ne garde que les décisions (pensée, outil, arguments) : les observations seront
    reproduites à l'exécution par les vrais outils, ce qui garde le replay honnête.
    """
    tape: list[dict[str, Any]] = []
    for step in steps:
        tool = step.get("tool")
        if not tool:
            continue
        tape.append(
            {
                "thought": str(step.get("thought", ""))[:400],
                "tool": tool,
                "args": step.get("args") or {},
            }
        )
    tape.append({"thought": "Livrable écrit et vérifié.", "final": str(summary or "Scénario terminé.")[:600]})
    target = scenario.root / (scenario.passes[0].get("cassette", "cassette.json") if scenario.passes else "cassette.json")
    target.write_text(json.dumps(tape, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def scenario_detail(slug: str) -> dict[str, Any]:
    """Tout ce qu'il faut pour éditer un scénario dans l'interface."""
    scenario = get_scenario(slug)
    fixtures = []
    fixture_dir = scenario.root / "fixtures"
    if fixture_dir.is_dir():
        fixtures = sorted(str(p.relative_to(fixture_dir)) for p in fixture_dir.rglob("*") if p.is_file())
    return {
        **scenario.as_summary(),
        "fixtures": fixtures,
        "passes_detail": scenario.passes,
        "editable": True,
        "network": scenario.network,
        "exec": scenario.exec_config,
        "inputs": scenario.inputs,
        "max_steps": scenario.max_steps,
        "objective": scenario.objective,
        "title": scenario.title,
        "blurb": scenario.blurb,
        "tags": scenario.tags,
        "overridden": scenario.overridden,
    }


EDITABLE_FIELDS = ("title", "blurb", "objective", "max_steps", "tags", "network", "exec", "inputs")


def update_scenario(slug: str, payload: dict[str, Any]) -> Scenario:
    """Édite un scénario utilisateur. Un scénario livré n'est pas modifiable : on le duplique."""
    scenario = get_scenario(slug)
    if scenario.builtin:
        # on n'écrit pas dans l'image : la modification vit dans une surcharge du dossier de données
        meta_path = override_path(slug)
        meta = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        meta["slug"] = slug
    else:
        meta_path = scenario.root / "scenario.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    network = payload.get("network")
    if isinstance(network, dict):
        mode = str(network.get("mode") or "deny")
        if mode not in ("deny", "allowlist", "open"):
            raise ValueError(f"mode réseau inconnu : {mode}")
        hosts = [str(h).strip().lower() for h in (network.get("hosts") or []) if str(h).strip()]
        if mode == "allowlist" and not hosts:
            raise ValueError("allowlist sans hôte : ajoute au moins un domaine")
        meta["network"] = (
            {"mode": "open", "justification": str(network.get("justification") or "déclaré dans l'interface")}
            if mode == "open"
            else {"mode": mode, "hosts": hosts}
        )
    if isinstance(payload.get("exec"), dict):
        meta["exec"] = {
            "allow_unsandboxed": bool(payload["exec"].get("allow_unsandboxed")),
            "reason": str(payload["exec"].get("reason") or ""),
        }
    if isinstance(payload.get("inputs"), dict):
        meta["inputs"] = {
            "dir": str(payload["inputs"].get("dir") or "").strip(),
            "feeds": [str(f).strip() for f in (payload["inputs"].get("feeds") or []) if str(f).strip()],
        }
    for key in ("title", "blurb", "objective"):
        if key in payload:
            value = str(payload[key]).strip()
            if not value:
                raise ValueError(f"{key} ne peut pas être vide")
            meta[key] = value
    if "max_steps" in payload:
        meta["max_steps"] = max(2, min(int(payload["max_steps"] or 10), 24))
    if "tags" in payload:
        meta["tags"] = [str(t).strip() for t in payload["tags"] if str(t).strip()]
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return get_scenario(slug)


def duplicate_scenario(slug: str, new_slug: str) -> Scenario:
    """Copie un scénario (y compris livré) vers le dossier utilisateur, à modifier ensuite."""
    source = get_scenario(slug)
    new_slug = str(new_slug or "").strip().lower()
    if not SLUG_RE.match(new_slug):
        raise ValueError("slug invalide : lettres minuscules, chiffres et tirets, 2 à 41 caractères")
    target_dir = user_scenarios_dir() / new_slug
    if target_dir.exists():
        raise ValueError(f"le scénario « {new_slug} » existe déjà")
    shutil.copytree(source.root, target_dir)
    meta_path = target_dir / "scenario.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["slug"] = new_slug
    meta["title"] = f"{meta.get('title', new_slug)} (copie)"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return get_scenario(new_slug)


def reset_scenario(slug: str) -> Scenario:
    """Retire la surcharge d'un scénario livré : il revient exactement tel qu'il est dans l'image."""
    scenario = get_scenario(slug)
    if not scenario.builtin:
        raise ValueError("seul un scénario livré a une surcharge à retirer")
    path = override_path(slug)
    if path.is_file():
        path.unlink()
    return get_scenario(slug)
