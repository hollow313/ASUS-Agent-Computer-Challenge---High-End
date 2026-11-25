"""Sandboxed tools available to the agent.

Every tool operates inside a single run workspace directory and refuses to touch
anything outside it. Tool results are returned as short human-readable strings:
that is exactly what the model sees as an observation.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MAX_OBSERVATION_CHARS = 2400


class NetworkPolicy:
    """Politique réseau du scénario : deny par défaut, allowlist explicite, open refusé sans accord.

    L'isolation réseau du noyau est assurée par le bac à sable ; ici on refuse avant même l'appel,
    pour que l'erreur soit lisible et pour qu'un `deny` ne dépende pas de la qualité de l'isolation.
    """

    def __init__(self, config: dict[str, Any] | None = None, events: list[dict[str, Any]] | None = None) -> None:
        config = config or {"mode": "deny"}
        self.mode = str(config.get("mode") or "deny")
        self.hosts = [str(h).strip().lower() for h in (config.get("hosts") or []) if str(h).strip()]
        self.justification = str(config.get("justification") or "")
        self.events = events if events is not None else []

    def allows(self, url: str) -> tuple[bool, str]:
        if not url.startswith(("http://", "https://")):
            return False, "seuls http(s) sont autorisés"
        if self.mode == "deny":
            return False, "scénario en mode deny : aucun accès réseau (les données sont locales)"
        if self.mode == "open":
            return True, "mode open"
        host = (urlparse(url).hostname or "").lower()
        if host in self.hosts:
            return True, f"hôte {host} dans l'allowlist"
        return False, f"hôte {host} absent de l'allowlist ({', '.join(self.hosts) or 'vide'})"

    def check(self, url: str, tool: str = "http_get") -> None:
        allowed, reason = self.allows(url)
        if not allowed:
            self.events.append({"event": "network_denied", "tool": tool, "url": url[:200], "reason": reason})
            raise ToolError(f"accès réseau refusé : {reason}")

    def as_dict(self) -> dict[str, Any]:
        return {"network_mode": self.mode, "hosts": list(self.hosts), "justification": self.justification}


class ToolError(RuntimeError):
    """Raised when a tool cannot complete. The message is fed back to the model."""


@dataclass(frozen=True)
class Tool:
    name: str
    signature: str
    description: str
    fn: Callable[..., str]


def _clip(text: str, limit: int = MAX_OBSERVATION_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [{len(text) - limit} caractères tronqués]"


class Sandbox:
    """Constrains every path to the run workspace."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative: str) -> Path:
        candidate = (self.root / str(relative)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ToolError(f"chemin hors du bac à sable refusé : {relative}")
        return candidate

    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.root))


def build_registry(
    sandbox: Sandbox,
    artifacts: list[str],
    skills: "SkillStore | None" = None,
    children_dir: "Path | None" = None,
    runs_dir: "Path | None" = None,
    parent_planner: Any = None,
    depth: int = 0,
    settings: Any = None,
    network: "NetworkPolicy | None" = None,
    runner: Any = None,
    events: "list[dict[str, Any]] | None" = None,
) -> dict[str, Tool]:
    """Return the tool registry bound to one sandbox (and, optionally, a skill store)."""

    def hint_for(missing: str) -> str:
        """Cherche un fichier de même nom ailleurs dans le bac à sable, pour corriger un chemin faux."""
        name = Path(str(missing)).name
        matches = [
            str(candidate.relative_to(sandbox.root))
            for candidate in sandbox.root.rglob(name)
            if candidate.is_file() and "delegations" not in candidate.parts
        ][:3]
        if matches:
            return f" — fichier présent ici : {', '.join(matches)}"
        files = [
            str(candidate.relative_to(sandbox.root))
            for candidate in sorted(sandbox.root.rglob("*.csv"))
            if "delegations" not in candidate.parts
        ][:5]
        return f" — aucun « {name} » ; CSV disponibles : {', '.join(files)}" if files else ""

    network = network or NetworkPolicy()
    events = events if events is not None else []

    def run(command: str) -> str:
        """Exécute une commande shell dans le dossier du run, sous bac à sable."""
        if runner is None:
            raise ToolError(
                "commande refusée dans ce scénario : il n'autorise pas l'exécution (champ exec absent). "
                "Utilise les outils d'analyse à disposition."
            )
        from .sandbox import SandboxError

        try:
            result = runner.run(command)
        except SandboxError as exc:
            events.append({"event": "exec_refused", "command": str(command)[:200], "reason": str(exc)})
            raise ToolError(str(exc)) from exc
        events.append(
            {
                "event": "exec",
                "command": str(command)[:200],
                "returncode": result.returncode,
                "isolation": result.isolation,
                "network": result.network,
                "duration_ms": result.duration_ms,
            }
        )
        return _clip(result.as_text(), MAX_OBSERVATION_CHARS)

    def note(path: Path) -> None:
        name = sandbox.rel(path)
        if name not in artifacts:
            artifacts.append(name)

    def skill_list() -> str:
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        rows = skills.ledger()
        if not rows:
            return "aucune procédure enregistrée"
        return "\n".join(
            f"- {row['name']} [{row['status']}] confiance {row['confidence']} % "
            f"({row['success']}/{row['uses']} succès) : {row['summary']}"
            for row in rows
        )

    def skill_recall(keyword: str = "") -> str:
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        return skills.format_recall(keyword, sandbox.root)

    def skill_write(name: str, content: str, check: str = "", topic: str = "") -> str:
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        skill = skills.write(name, content, check, topic)
        claim = f" contrat « {check} »" if check else " sans contrat de vérification"
        return (
            f"procédure « {skill.name} » enregistrée ({len(content)} caractères){claim} "
            f"confiance {round(100 * skill.confidence)} %"
        )

    def skill_revise(name: str, content: str, check: str = "", reason: str = "") -> str:
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        revised = skills.revise(name, content, check, reason)
        if revised is None:
            raise ToolError(f"procédure inconnue : {name}")
        state = "réactivée" if revised.status == "active" else "toujours stale (contrat non vérifié)"
        return (
            f"procédure « {revised.name} » révisée, {state}, "
            f"révision n°{revised.meta.get('revisions', '1')}, confiance {round(100 * revised.confidence)} %"
        )

    def skill_resolve(topic: str = "") -> str:
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        decisions = skills.resolve_conflicts(topic or None)
        if not decisions:
            return "aucun conflit de procédures détecté"
        return "\n".join(
            f"- {item['topic']} : {item['winner']} garde la main "
            f"(confiance {item['winner_confidence']} % contre {item['loser_confidence']} %), "
            f"{item['loser']} passe superseded"
            for item in decisions
        )

    def maintenance_run() -> str:
        """Lance une passe d'entretien : réparation, arbitrage par preuve, retrait."""
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        from .maintenance import Maintainer  # import local

        maintainer = Maintainer(skills, sandbox.root)
        report = maintainer.run_once()
        if not report.changed:
            return f"entretien terminé, rien à corriger sur {report.scanned} procédures"
        parts = []
        if report.repaired:
            parts.append(
                "réparées : " + ", ".join(f"{i['procedure']} ({i['de']} -> {i['vers']})" for i in report.repaired)
            )
        if report.superseded:
            parts.append(
                "arbitrées : " + ", ".join(f"{i['winner']} > {i['loser']}" for i in report.superseded)
            )
        if report.retired:
            parts.append("retirées : " + ", ".join(report.retired))
        return " | ".join(parts)

    def skill_feedback(name: str, ok: bool = True) -> str:
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        skill = skills.feedback(name, bool(ok))
        if skill is None:
            raise ToolError(f"procédure inconnue : {name}")
        return (
            f"procédure « {skill.name} » mise à jour : {skill.successes}/{skill.uses} succès, "
            f"confiance {round(100 * skill.confidence)} %, statut {skill.status}"
        )

    def skill_prune() -> str:
        if skills is None:
            raise ToolError("mémoire procédurale désactivée dans ce run")
        retired = skills.prune()
        return (
            f"{len(retired)} procédure(s) mise(s) à la retraite : {', '.join(retired)}"
            if retired
            else "aucune procédure à mettre à la retraite"
        )

    def spawn_agent(objective: str, name: str = "", source: str = "", max_steps: int = 6) -> str:
        """Délègue un objectif à un sous-agent, avec son propre budget et sa propre trace.

        Deux modes, dans cet ordre :

        1. une cassette enregistrée existe pour ce nom : le sous-agent rejoue une trace connue,
           utile pour une démonstration déterministe ;
        2. sinon, si le run courant parle à un vrai modèle, le sous-agent hérite du même endpoint
           et travaille pour de bon, dans `delegations/<nom>/`, avec son propre budget.

        Le parent ne partage ni budget ni journal avec ses enfants, et la profondeur est bornée
        pour qu'une délégation ne devienne pas une récursion infinie.
        """
        if children_dir is None:
            raise ToolError("délégation désactivée dans ce run")
        if depth >= 2:
            raise ToolError(
                "profondeur de délégation maximale atteinte (3 niveaux) : traite cette zone toi-même"
            )
        from .agent import Agent  # import local : éviter le cycle agent -> tools
        from .planners import ReplayPlanner

        label = _agent_slug(name or source or objective)
        cassette_path = Path(children_dir) / f"{label}.json"
        tape = json.loads(cassette_path.read_text(encoding="utf-8")) if cassette_path.exists() else None

        if tape is not None:
            child_planner = ReplayPlanner(tape)
            mode = "replay"
        else:
            factory = getattr(parent_planner, "child", None)
            child_planner = factory() if callable(factory) else None
            if child_planner is None:
                available = sorted(p.stem for p in Path(children_dir).glob("*.json"))
                raise ToolError(
                    f"aucun sous-agent nommé « {label} » : en mode replay, utilise un nom existant "
                    f"({', '.join(available) or 'aucun'}) ; en mode réel, n'importe quel nom est accepté"
                )
            mode = "live"

        child_ws = sandbox.root / "delegations" / label
        if child_ws.exists() and any(child_ws.iterdir()):
            raise ToolError(
                f"le sous-agent « {label} » a déjà travaillé dans ce run : lis ses livrables "
                f"(delegations/{label}/) au lieu de le relancer"
            )
        child_ws.mkdir(parents=True, exist_ok=True)
        # le sous-agent voit les mêmes entrées que son parent, dans son propre bac à sable
        for item in sandbox.root.iterdir():
            if item.name == "delegations":
                continue
            destination = child_ws / item.name
            if item.is_dir():
                shutil.copytree(item, destination, dirs_exist_ok=True)
            elif item.is_file():
                shutil.copy2(item, destination)
        child = Agent(
            planner=child_planner,
            workspace=child_ws,
            runs_dir=Path(runs_dir or sandbox.root.parent),
            max_steps=max(1, min(int(max_steps), 8)),
            children_dir=children_dir,
            delegation_depth=depth + 1,
        )
        child.skills = skills
        # le sous-agent ne devine pas les chemins : il reçoit l'inventaire de son parent
        inventory = _inventory(sandbox.root)
        brief = f"{objective}\n\nFichiers disponibles (chemins relatifs à la racine du bac à sable) :\n{inventory}"
        result = child.run(brief, run_id=f"child-{label}")
        for artifact in result.artifacts:
            note(child_ws / artifact)
        errors = sum(1 for step in result.steps if step.error)
        produced = ", ".join(f"delegations/{label}/{a}" for a in result.artifacts) or "aucun"
        return (
            f"sous-agent « {label} » ({mode}) : statut {result.status}, "
            f"{len(result.steps)} étapes, {errors} erreur(s), livrables : {produced} "
            f"| {result.summary[:400]}"
        )

    def _inventory(root: Path, limit: int = 40) -> str:
        """Liste courte des entrées visibles, pour que le sous-agent travaille sur de vrais chemins."""
        rows: list[str] = []
        for item in sorted(root.rglob("*")):
            if "delegations" in item.parts:
                continue
            rel = item.relative_to(root).as_posix()
            rows.append(rel + ("/" if item.is_dir() else ""))
            if len(rows) >= limit:
                rows.append("…")
                break
        return "\n".join(f"- {row}" for row in rows) or "- (bac à sable vide)"

    def _agent_slug(value: str) -> str:
        """Nom de dossier stable à partir d'un objectif ou d'un nom libre."""
        text = str(value or "sous-agent").strip().lower()
        text = re.sub(r"[^a-z0-9]+", "-", text.replace("é", "e").replace("è", "e").replace("ê", "e").replace("à", "a").replace("ç", "c"))
        return (text.strip("-")[:40] or "sous-agent")

    def mail_list(limit: int = 8, mailbox: str = "") -> str:
        """Lit les derniers messages d'une vraie boîte IMAP, si elle est configurée."""
        from .mailbox import MailError, list_messages

        if settings is None or not settings.mail.host:
            raise ToolError(
                "aucune boîte IMAP configurée : renseigne hôte, utilisateur et mot de passe dans /settings"
            )
        try:
            messages = list_messages(settings.mail, limit=max(1, min(int(limit), 25)), mailbox=mailbox)
        except MailError as exc:
            raise ToolError(str(exc)) from exc
        if not messages:
            return "boîte vide ou dossier sans message"
        rows = []
        for item in messages:
            rows.append(
                f"- uid {item['uid']} | {item['de'][:60]} | {item['objet'][:90]} | {item['date'][:31]}\n"
                f"  {item['extrait'][:200]}"
            )
        return "\n".join(rows)

    def mail_move(uid: str, folder: str = "") -> str:
        """Déplace un message vers un dossier d'archive."""
        from .mailbox import MailError, move_message

        if settings is None or not settings.mail.host:
            raise ToolError("aucune boîte IMAP configurée : voir /settings")
        try:
            return move_message(settings.mail, str(uid), folder)
        except MailError as exc:
            raise ToolError(str(exc)) from exc

    def inputs_list(path: str = "inputs") -> str:
        """Liste les données d'entrée copiées dans le run (CSV, flux, pièces)."""
        target = sandbox.resolve(path)
        if not target.is_dir():
            raise ToolError(f"aucun dossier d'entrée « {path} » : configure-le dans /settings")
        rows = [f"{item.name}  {item.stat().st_size} o" for item in sorted(target.iterdir()) if item.is_file()]
        return "\n".join(rows) or "(dossier d'entrée vide)"

    def csv_dir_profile(path: str = "inputs") -> str:
        """Profile tous les CSV d'un dossier et additionne les volumes d'une colonne."""
        target = sandbox.resolve(path)
        if not target.is_dir():
            raise ToolError(f"dossier introuvable : {path}")
        files = sorted(target.glob("*.csv"))
        if not files:
            raise ToolError(f"aucun CSV dans {path}")
        rows = []
        for file in files:
            try:
                with file.open(newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    records = list(reader)
            except (OSError, csv.Error) as exc:
                rows.append(f"- {file.name} : illisible ({exc})")
                continue
            numeric = [
                column
                for column in (reader.fieldnames or [])
                if records and _is_number((records[0].get(column) or "0").replace(",", "."))
            ]
            totals = {column: sum(float((r.get(column) or "0").replace(",", ".")) for r in records) for column in numeric}
            detail = ", ".join(f"{k}={round(v, 2)}" for k, v in totals.items()) or "aucune colonne numérique"
            rows.append(f"- {file.name} : {len(records)} lignes, colonnes {', '.join(reader.fieldnames or [])} | totaux {detail}")
        return "\n".join(rows)

    def fs_list(path: str = ".") -> str:
        target = sandbox.resolve(path)
        if not target.exists():
            entries = sorted(item.name + ("/" if item.is_dir() else "") for item in sandbox.root.iterdir())
            raise ToolError(
                f"introuvable : {path}{hint_for(path)}"
                + (f" — à la racine du bac à sable : {', '.join(entries[:12])}" if entries else "")
            )
        if target.is_file():
            return f"{path} est un fichier ({target.stat().st_size} octets)"
        rows = []
        for entry in sorted(target.iterdir()):
            kind = "dir " if entry.is_dir() else "file"
            size = "" if entry.is_dir() else f"  {entry.stat().st_size:>7} o"
            rows.append(f"{kind}  {entry.name}{size}")
        return "\n".join(rows) or "(dossier vide)"

    def fs_read(path: str, max_chars: int = 4000) -> str:
        target = sandbox.resolve(path)
        if not target.is_file():
            raise ToolError(f"fichier introuvable : {path}{hint_for(path)}")
        text = target.read_text(encoding="utf-8", errors="replace")
        head = text[: int(max_chars)]
        if len(text) > len(head):
            head += f"\n… [{len(text) - len(head)} caractères non affichés]"
        return f"# {path} ({len(text)} caractères)\n{head}"

    def fs_write(path: str, content: str) -> str:
        target = sandbox.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        note(target)
        return f"écrit {path}, {target.stat().st_size} octets"

    def fs_move(src: str, dst: str) -> str:
        source, dest = sandbox.resolve(src), sandbox.resolve(dst)
        if not source.exists():
            raise ToolError(f"source introuvable : {src}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise ToolError(
                f"destination déjà présente : {dst}. Choisis un autre nom, ou fs_write pour remplacer le contenu."
            )
        try:
            shutil.move(str(source), str(dest))
        except (OSError, shutil.Error) as exc:
            raise ToolError(f"déplacement impossible de {src} vers {dst} : {exc}") from exc
        note(dest)
        return f"déplacé {src} → {dst}"


    MAX_IMAGE_BYTES = 1_500_000

    def _image_header(data: bytes) -> tuple[str, int, int] | None:
        """Format, largeur, hauteur, lus dans l'en-tête. Aucune dépendance, aucun décodage complet."""
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            return "PNG", width, height
        if data[:2] == b"\xff\xd8":
            index = 2
            while index < len(data) - 9:
                if data[index] != 0xFF:
                    index += 1
                    continue
                marker = data[index + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):  # SOF0 a SOF3
                    height = int.from_bytes(data[index + 5 : index + 7], "big")
                    width = int.from_bytes(data[index + 7 : index + 9], "big")
                    return "JPEG", width, height
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    index += 2
                    continue
                length = int.from_bytes(data[index + 2 : index + 4], "big")
                index += 2 + max(length, 2)
            return "JPEG", 0, 0
        return None

    def image_probe(path: str) -> str:
        """Mesure une image : format, dimensions, poids. Le fait, quand le modèle donne la lecture."""
        target = sandbox.resolve(path)
        if not target.is_file():
            raise ToolError(f"image introuvable : {path}{hint_for(path)}")
        size = target.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise ToolError(
                f"image trop lourde pour un modèle local : {size / 1_000_000:.1f} Mo, "
                f"plafond {MAX_IMAGE_BYTES / 1_000_000:.1f} Mo. Réduis la capture avant de la relancer."
            )
        head = target.read_bytes()[:65_536]
        parsed = _image_header(head)
        if parsed is None:
            raise ToolError(
                f"ce fichier n'est pas une image lisible (PNG ou JPEG attendu) : {path}. "
                "Vérifie l'extension et le contenu."
            )
        fmt, width, height = parsed
        if not width or not height:
            raise ToolError(f"dimensions illisibles dans l'en-tête de {path}")
        # une image d'entrée n'est pas un livrable : on ne la déclare pas comme artefact
        return (
            f"{width} x {height}, {size / 1000:.0f} ko, {fmt}, ratio {width / height:.2f}. "
            f"Chaque constat doit citer une zone de cette image, en pixels."
        )

    def csv_profile(path: str) -> str:
        target = sandbox.resolve(path)
        if not target.is_file():
            raise ToolError(f"csv introuvable : {path}{hint_for(path)}")
        with target.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            return "aucune ligne de données"
        columns = list(rows[0].keys())
        numeric = [c for c in columns if all(_is_number(r.get(c)) for r in rows)]
        lines = [f"{len(rows)} lignes, {len(columns)} colonnes", f"colonnes : {', '.join(columns)}"]
        for column in numeric:
            values = [float(r[column]) for r in rows]
            lines.append(
                f"{column}: min={min(values):.2f} max={max(values):.2f} "
                f"total={sum(values):.2f} moyenne={sum(values) / len(values):.2f}"
            )
        return "\n".join(lines)

    def chart_bar(path: str, label_column: str, value_column: str, output: str, title: str = "Graphique") -> str:
        target = sandbox.resolve(path)
        if not target.is_file():
            raise ToolError(f"csv introuvable : {path}{hint_for(path)}")
        with target.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        series = [(r[label_column], float(r[value_column])) for r in rows if _is_number(r.get(value_column))]
        if not series:
            raise ToolError("aucune valeur numérique exploitable")
        dest = sandbox.resolve(output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_bar_svg(series, title, value_column), encoding="utf-8")
        note(dest)
        return f"graphique écrit dans {output} ({len(series)} barres)"

    def rss_rank(paths: list[str], top_n: int = 6) -> str:
        items: list[tuple[str, str, str]] = []
        for raw in paths:
            if str(raw).startswith(("http://", "https://")):
                network.check(str(raw), "rss_rank")
            target = sandbox.resolve(raw)
            if not target.is_file():
                feed_dir = sandbox.root / "feeds"
                available = sorted(x.name for x in feed_dir.glob("*")) if feed_dir.is_dir() else []
                hint = f" — flux présents dans feeds/ : {', '.join(available)}" if available else ""
                raise ToolError(
                    f"flux introuvable : {raw} (un chemin exact par fichier, pas de joker){hint}"
                )
            try:
                root = ET.fromstring(target.read_text(encoding="utf-8", errors="replace"))
            except ET.ParseError as exc:
                raise ToolError(f"XML invalide dans {raw} : {exc}") from exc
            for node in root.iter("item"):
                title = (node.findtext("title") or "").strip()
                summary = (node.findtext("description") or "").strip()
                items.append((title, summary, target.name))
        scored = sorted(((len(summary), t, s, f) for t, s, f in items), reverse=True)
        lines = [f"{len(items)} entrées lues dans {len(paths)} flux, classées par densité d'information"]
        for _, title, summary, feed in scored[: int(top_n)]:
            lines.append(f"- [{feed}] {title} :: {summary[:220]}")
        return "\n".join(lines)

    def tts_speak(text: str, output: str = "narration.mp3", voice: str = "alloy") -> str:
        """Génère un fichier audio depuis un texte, via un endpoint /audio/speech.

        Désactivé si AGENTDEMO_TTS_URL n'est pas défini : la démo reste exécutable sans
        dépendance réseau, et l'échec est explicite plutôt que simulé.
        """
        base = os.environ.get("AGENTDEMO_TTS_URL", "").rstrip("/")
        if not base:
            raise ToolError(
                "synthèse vocale non configurée (AGENTDEMO_TTS_URL) : l'outil échoue proprement "
                "au lieu de faire semblant"
            )
        payload = {"model": os.environ.get("AGENTDEMO_TTS_MODEL", "tts-1"), "input": str(text), "voice": voice}
        request = urllib.request.Request(
            f"{base}/audio/speech",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {os.environ.get('AGENTDEMO_TTS_KEY', '')}"}
                   if os.environ.get("AGENTDEMO_TTS_KEY") else {}),
            },
        )
        dest = sandbox.resolve(output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                dest.write_bytes(response.read())
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ToolError(f"synthèse vocale impossible : {exc}") from exc
        note(dest)
        return f"audio écrit dans {output} ({dest.stat().st_size} octets)"


    def _html_to_text(html: str, limit: int = 4000) -> str:
        """HTML lisible : les balises partent, les liens restent.

        Un `http_get` qui rend deux mille caractères de balises ne sert à rien : le modèle écrit
        n'importe quoi ensuite. On garde le texte, le titre, et jusqu'à quinze liens avec leur libellé.
        """
        import html as html_module
        import re as _re

        body = _re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
        links = _re.findall(r'(?is)<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body)
        title = _re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
        text = _re.sub(r"(?s)<[^>]+>", " ", body)
        text = html_module.unescape(text)
        text = _re.sub(r"[ \t\r\f\v]+", " ", text)
        text = _re.sub(r"\n\s*\n+", "\n", text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned = "\n".join(lines)
        seen: list[str] = []
        for href, label in links:
            label = html_module.unescape(_re.sub(r"(?s)<[^>]+>", "", label)).strip()
            if not label or len(label) < 20 or href.startswith(("#", "javascript:", "mailto:")):
                continue
            entry = f"- {label[:110]} — {href}"
            if entry not in seen:
                seen.append(entry)
            if len(seen) >= 25:
                break
        head = f"titre : {html_module.unescape(title.group(1)).strip()}\n" if title else ""
        # les liens d'abord : sur une page d'actualités, ce sont eux les titres, la navigation
        # du site ne dit rien d'utile et occupe tout le budget de caractères
        block = ""
        if seen:
            block = "liens :\n" + "\n".join(seen) + "\n\ntexte :\n"
        return _clip(head + block + cleaned, limit)

    def http_get(url: str, max_chars: int = 4000) -> str:
        network.check(url, "http_get")
        request = urllib.request.Request(url, headers={"User-Agent": "agent-computer-demo/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                body = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ToolError(f"échec réseau : {exc}") from exc
        except ValueError as exc:  # URL refusée par urllib (schéma, hôte)
            raise ToolError(f"URL invalide : {exc}") from exc
        if "<html" in body[:600].lower() or "<!doctype" in body[:600].lower():
            return _html_to_text(body, int(max_chars))
        return _clip(body, int(max_chars))

    registry = {
        "fs_list": Tool("fs_list", "fs_list(path)", "liste un dossier du bac à sable", fs_list),
        "mail_list": Tool(
            "mail_list",
            "mail_list(limit?, mailbox?)",
            "lit les derniers messages d'une vraie boîte IMAP (expéditeur, objet, extrait)",
            mail_list,
        ),
        "mail_move": Tool(
            "mail_move",
            "mail_move(uid, folder?)",
            "déplace un message IMAP vers le dossier d'archive configuré",
            mail_move,
        ),
        "inputs_list": Tool(
            "inputs_list",
            "inputs_list(path?)",
            "liste les données d'entrée du run (dossier inputs/)",
            inputs_list,
        ),
        "csv_dir_profile": Tool(
            "csv_dir_profile",
            "csv_dir_profile(path?)",
            "profile tous les CSV d'un dossier et calcule les totaux",
            csv_dir_profile,
        ),
        "fs_read": Tool("fs_read", "fs_read(path, max_chars?)", "lit un fichier texte", fs_read),
        "fs_write": Tool("fs_write", "fs_write(path, content)", "écrit un fichier (livrable)", fs_write),
        "fs_move": Tool("fs_move", "fs_move(src, dst)", "déplace un fichier", fs_move),
        "csv_profile": Tool("csv_profile", "csv_profile(path)", "statistiques d'un CSV", csv_profile),
        "chart_bar": Tool(
            "chart_bar",
            "chart_bar(path, label_column, value_column, output, title?)",
            "génère un graphique SVG à partir d'un CSV",
            chart_bar,
        ),
        "rss_rank": Tool("rss_rank", "rss_rank(paths[], top_n?)", "lit des flux RSS et les classe", rss_rank),
        "image_probe": Tool(
            "image_probe",
            "image_probe(path)",
            "mesure une image du bac à sable : format, dimensions en pixels, poids, et rappelle que "
            "chaque constat doit citer une zone. À appeler avant de décrire une capture",
            image_probe,
        ),
        "http_get": Tool(
            "http_get",
            "http_get(url, max_chars?)",
            "GET HTTP, soumis à la politique réseau du scénario (deny par défaut)",
            http_get,
        ),
        "tts_speak": Tool(
            "tts_speak",
            "tts_speak(text, output?, voice?)",
            "génère un fichier audio depuis un texte (endpoint /audio/speech, désactivé par défaut)",
            tts_speak,
        ),
        "spawn_agent": Tool(
            "spawn_agent",
            "spawn_agent(objective, name?, source?, max_steps?)",
            "délègue une sous-tâche à un sous-agent qui a son propre budget, sa propre trace et "
            "son dossier delegations/<nom>/ ; n'importe quel nom en mode réel",
            spawn_agent,
        ),
        "skill_list": Tool("skill_list", "skill_list()", "liste les procédures déjà apprises", skill_list),
        "skill_recall": Tool(
            "skill_recall",
            "skill_recall(keyword?)",
            "relit une procédure apprise avant d'agir (mémoire persistante)",
            skill_recall,
        ),
        "skill_write": Tool(
            "skill_write",
            "skill_write(name, content, check?, topic?)",
            "enregistre une procédure, avec contrat de vérification et sujet optionnels",
            skill_write,
        ),
        "skill_revise": Tool(
            "skill_revise",
            "skill_revise(name, content, check?, reason?)",
            "réécrit une procédure périmée, la réactive seulement si le nouveau contrat passe",
            skill_revise,
        ),
        "skill_resolve": Tool(
            "skill_resolve",
            "skill_resolve(topic?)",
            "arbitre des procédures contradictoires : la confiance la plus haute gagne",
            skill_resolve,
        ),
        "skill_feedback": Tool(
            "skill_feedback",
            "skill_feedback(name, ok?)",
            "enregistre le succès ou l'échec d'une procédure, met à jour sa confiance",
            skill_feedback,
        ),
        "maintenance_run": Tool(
            "maintenance_run",
            "maintenance_run()",
            "lance une passe d'entretien des procédures (réparer, arbitrer, retirer)",
            maintenance_run,
        ),
        "skill_prune": Tool(
            "skill_prune",
            "skill_prune()",
            "met à la retraite les procédures obsolètes ou peu fiables (réversible)",
            skill_prune,
        ),
    }
    if runner is not None:
        registry["run"] = Tool(
            "run",
            "run(command)",
            "exécute une commande shell dans le dossier du run, sous bac à sable (bwrap, unshare)",
            run,
        )
    return registry


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _bar_svg(series: list[tuple[str, float]], title: str, unit: str) -> str:
    width, height = 640, 340
    left, top, bottom = 60, 50, 40
    plot_w, plot_h = width - left - 20, height - top - bottom
    peak = max(value for _, value in series) or 1.0
    slot = plot_w / len(series)
    bar_w = min(64, slot * 0.6)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#12151c"/>',
        f'<text x="{left}" y="28" fill="#e8ecf4" font-family="monospace" font-size="15">{_escape(title)}</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{width - 20}" y2="{top + plot_h}" stroke="#39404f"/>',
    ]
    for index, (label, value) in enumerate(series):
        bar_h = (value / peak) * plot_h
        x = left + index * slot + (slot - bar_w) / 2
        y = top + plot_h - bar_h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="#5b8cff" rx="3"/>')
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" fill="#9aa6bd" font-family="monospace" '
            f'font-size="11" text-anchor="middle">{value:.0f}</text>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{top + plot_h + 18:.1f}" fill="#7c8698" font-family="monospace" '
            f'font-size="10" text-anchor="middle">{_escape(label[:13])}</text>'
        )
    parts.append(
        f'<text x="{width - 20}" y="{height - 8}" fill="#5e6675" font-family="monospace" '
        f'font-size="10" text-anchor="end">{_escape(unit)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
