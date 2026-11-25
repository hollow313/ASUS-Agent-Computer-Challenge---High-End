"""Une consigne libre, sans scénario écrit à la main.

Même boucle, même bac à sable, même journal qu'un scénario : ce qui change est seulement la **source du
contrat**. Un scénario livré est un dossier sur disque ; ici, le contrat est construit en mémoire à partir
d'une phrase, et il disparaît après le run.

Trois règles, tenues par le code et pas par le prompt :

* une consigne vide est refusée ;
* une consigne de plus de 600 caractères est refusée : au-delà, c'est une pièce jointe, pas une consigne,
  et il faut un scénario ;
* un run qui n'écrit aucun fichier n'est jamais `done` : il est `blocked`, même s'il a bien parlé.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import unicodedata
from pathlib import Path

from .scenarios_loader import Scenario

MAX_CHARS = 600
DEFAULT_MAX_STEPS = 14
SLUG_PREFIX = "ask-"


class AskError(ValueError):
    """Consigne refusée, avec un message qui dit quoi faire."""


def _normalise(text: str) -> str:
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(ch)
    )
    return re.sub(r"\s+", " ", stripped).strip()


def slug_for(objective: str) -> str:
    """Le même texte donne le même slug, sans horloge : sinon `--resume` ne retrouve rien."""
    digest = hashlib.sha1(_normalise(objective).encode("utf-8")).hexdigest()
    return f"{SLUG_PREFIX}{digest[:8]}"


def validate(objective: str) -> str:
    text = (objective or "").strip()
    if not text:
        raise AskError(
            "l'objectif est vide : passe une consigne entre guillemets, par exemple "
            'ask "classe les trois CSV du dossier et écris un comparatif"'
        )
    if len(text) > MAX_CHARS:
        raise AskError(
            f"consigne trop longue : {len(text)} caractères, plafond {MAX_CHARS}. Au-delà, ce n'est plus "
            "une consigne mais une pièce jointe : dépose les fichiers dans le dossier d'entrée et utilise "
            "un scénario (python3 -m agentdemo scenarios)."
        )
    return text


def network_for(hosts: list[str] | None = None, allow_open: bool = False, confirmed: bool = False) -> dict:
    """Réseau refusé par défaut ; une allowlist explicite, jamais `open` par accident.

    `open` demande une confirmation : un script lancé sans terminal ne peut pas l'obtenir, donc il est
    refusé plutôt que d'ouvrir le réseau dans le dos de l'opérateur.
    """
    if allow_open:
        if not confirmed:
            raise AskError(
                "réseau ouvert refusé : ajoute --yes ou réponds oui au terminal. Une allowlist "
                "(--allow hote) est préférable quand on sait quels hôtes sont nécessaires."
            )
        return {"mode": "open", "hosts": []}
    hosts = [h.strip() for h in (hosts or []) if h and h.strip()]
    if hosts:
        return {"mode": "allowlist", "hosts": hosts}
    return {"mode": "deny", "hosts": []}


def build(
    objective: str,
    *,
    data_dir: Path,
    network: dict | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    title: str = "",
) -> Scenario:
    """Un scénario éphémère : même contrat, aucune cassette, aucun dossier de fixtures."""
    text = validate(objective)
    slug = slug_for(text)
    root = Path(data_dir) / "ask" / slug
    root.mkdir(parents=True, exist_ok=True)
    return Scenario(
        slug=slug,
        title=title or (text[:60] + ("…" if len(text) > 60 else "")),
        blurb="consigne libre, sans cassette",
        objective=text,
        max_steps=max(2, min(int(max_steps or DEFAULT_MAX_STEPS), 24)),
        tags=["ask"],
        root=root,
        passes=[{"label": "consigne libre", "cassette": None}],
        network=dict(network or {"mode": "deny"}),
        exec_config={},
        inputs={},
        require_approval=False,
        vision={},
        overridden=False,
    )


def enforce_deliverable(result) -> None:
    """Un run libre qui n'écrit rien n'a rien produit : il est bloqué, pas terminé.

    La règle est ici et pas dans le prompt : un modèle qui répond « voici ce que je ferais » obtient le
    même statut qu'un agent qui refuse d'agir.
    """
    if result.status == "done" and not result.artifacts:
        result.status = "blocked"
        result.summary = (
            "Aucun fichier écrit : la consigne demandait un livrable, la réponse seule ne compte pas. "
            f"Bilan du modèle : {result.summary[:200]}"
        )


def scratch_root() -> Path:
    """Dossier temporaire pour une consigne jetable (tests, essais)."""
    return Path(tempfile.mkdtemp(prefix="vigie-ask-"))
