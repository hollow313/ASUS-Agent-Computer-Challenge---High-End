"""Routage : décider quel modèle traite quelle tâche, et le prouver.

Un routeur n'est pas une abstraction, c'est une politique écrite. Ce module la stocke dans
`routing.json`, la résout de façon déterministe, et journalise la décision.

Ordre de résolution, du plus fort au plus faible :

1. **forçage manuel** (`override`) : un modèle imposé à la main, pour une démo ou un test ;
2. **règles**, dans l'ordre du fichier : la première qui matche gagne ;
3. **cible par défaut**.

Types de règle disponibles :

* `always` : attrape tout, sert de garde-fou en fin de liste ;
* `scenario` : un slug de scénario (`cyber-brief`, `delegation`, ...) ;
* `keyword` : expression régulière cherchée dans l'objectif, insensible à la casse ;
* `sensitive` : l'objectif parle de données qui ne doivent pas sortir (`client`, `personnel`,
  `confidentiel`, ...). Ces mots sont configurables.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SENSITIVE_WORDS = [
    "client",
    "personnel",
    "personnelle",
    "confidentiel",
    "sensible",
    "rgpd",
    "iban",
    "médical",
    "medical",
    "archive familiale",
]
MATCH_KINDS = ("always", "scenario", "keyword", "sensitive")


class RoutingError(ValueError):
    pass


@dataclass
class Target:
    id: str
    label: str
    base_url: str
    model: str
    kind: str = "local"  # "local" ou "cloud"
    api_key: str = ""

    def validate(self) -> None:
        if not self.id or not re.fullmatch(r"[a-z0-9_-]{2,32}", self.id):
            raise RoutingError(f"identifiant de cible invalide : {self.id!r}")
        if self.kind not in ("local", "cloud"):
            raise RoutingError(f"type de cible inconnu : {self.kind!r}")
        if self.base_url and not self.base_url.startswith(("http://", "https://")):
            raise RoutingError(f"URL invalide pour {self.id} : {self.base_url!r}")
        if not self.model:
            raise RoutingError(f"modèle manquant pour {self.id}")

    @classmethod
    def from_public(cls, item: dict[str, Any]) -> "Target":
        """Reconstruit une cible depuis ce que l'interface a reçu.

        `/api/routing` renvoie des champs calculés (`has_key`) que l'interface renvoie tels quels
        au moment d'enregistrer : les ignorer évite un refus incompréhensible sur un simple ajout.
        """
        return cls(
            id=str(item.get("id") or ""),
            label=str(item.get("label") or item.get("id") or ""),
            base_url=str(item.get("base_url") or ""),
            model=str(item.get("model") or ""),
            kind=str(item.get("kind") or "local"),
            api_key=str(item.get("api_key") or ""),
        )

    def as_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "base_url": self.base_url,
            "model": self.model,
            "kind": self.kind,
            "has_key": bool(self.api_key),
        }


@dataclass
class Rule:
    match: str
    value: str
    target: str
    note: str = ""

    def validate(self, target_ids: set[str]) -> None:
        if self.match not in MATCH_KINDS:
            raise RoutingError(f"type de règle inconnu : {self.match!r}")
        if self.target not in target_ids:
            raise RoutingError(f"la règle pointe sur une cible absente : {self.target!r}")
        if self.match == "keyword":
            try:
                re.compile(self.value)
            except re.error as exc:
                raise RoutingError(f"expression régulière invalide : {self.value!r} ({exc})") from exc


@dataclass
class Decision:
    target: Target
    reason: str
    matched: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.as_public(),
            "reason": self.reason,
            "matched": self.matched,
            "decided_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


@dataclass
class RoutingTable:
    targets: list[Target] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    default_target: str = ""
    override: str = ""
    sensitive_words: list[str] = field(default_factory=lambda: list(DEFAULT_SENSITIVE_WORDS))
    history: list[dict[str, Any]] = field(default_factory=list)

    # ---------- persistance ----------
    @classmethod
    def load(cls, path: Path) -> "RoutingTable":
        path = Path(path)
        if not path.exists():
            return cls.default()
        raw = json.loads(path.read_text(encoding="utf-8"))
        table = cls(
            targets=[Target.from_public(item) for item in raw.get("targets", [])],
            rules=[Rule(**{k: item.get(k, "") for k in ("match", "value", "target", "note")}) for item in raw.get("rules", [])],
            default_target=raw.get("default_target", ""),
            override=raw.get("override", ""),
            sensitive_words=list(raw.get("sensitive_words") or DEFAULT_SENSITIVE_WORDS),
            history=list(raw.get("history", []))[-50:],
        )
        table.validate()
        return table

    def save(self, path: Path) -> None:
        self.validate()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(
                {
                    "targets": [asdict(target) for target in self.targets],
                    "rules": [asdict(rule) for rule in self.rules],
                    "default_target": self.default_target,
                    "override": self.override,
                    "sensitive_words": self.sensitive_words,
                    "history": self.history[-50:],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @classmethod
    def default(cls) -> "RoutingTable":
        return cls(
            targets=[
                Target("local-rapide", "LM Studio, Qwen 7B", "http://MON-IP:1234/v1", "qwen2.5-coder-7b", "local"),
                Target("local-gros", "LM Studio, Qwen 14B", "http://MON-IP:1234/v1", "qwen2.5-coder-14b", "local"),
                Target("cloud", "API compatible OpenAI", "https://api.exemple.invalid/v1", "modele-cloud", "cloud"),
            ],
            rules=[
                Rule("sensitive", "", "local-gros", "ce qui ne doit pas sortir reste en local"),
                Rule("scenario", "local-audit", "local-gros", "audit de sécurité : rien ne sort"),
                Rule("scenario", "dataset-report", "cloud", "analyse de données non sensible"),
                Rule("keyword", r"r[ée]sum|tri|classement", "local-rapide", "tâche mécanique, le petit modèle suffit"),
                Rule("always", "", "local-gros", "par défaut, le modèle local le plus capable"),
            ],
            default_target="local-gros",
        )

    # ---------- validation ----------
    def validate(self) -> None:
        if not self.targets:
            raise RoutingError("aucune cible configurée")
        ids = set()
        for target in self.targets:
            target.validate()
            if target.id in ids:
                raise RoutingError(f"identifiant de cible en double : {target.id}")
            ids.add(target.id)
        for rule in self.rules:
            rule.validate(ids)
        if self.default_target and self.default_target not in ids:
            raise RoutingError(f"cible par défaut absente : {self.default_target}")
        if self.override and self.override not in ids:
            raise RoutingError(f"forçage manuel sur une cible absente : {self.override}")

    # ---------- résolution ----------
    def resolve(self, objective: str, scenario: str = "") -> Decision:
        self.validate()
        by_id = {target.id: target for target in self.targets}

        if self.override:
            return Decision(
                by_id[self.override], f"forçage manuel vers {self.override}", "override"
            )

        text = objective or ""
        for rule in self.rules:
            if self._matches(rule, text, scenario):
                return Decision(by_id[rule.target], rule.note or f"règle {rule.match}", f"{rule.match}:{rule.value}")

        target = by_id.get(self.default_target) or self.targets[0]
        return Decision(target, "aucune règle ne matche, cible par défaut", "default")

    def _matches(self, rule: Rule, text: str, scenario: str) -> bool:
        if rule.match == "always":
            return True
        if rule.match == "scenario":
            return scenario == rule.value
        if rule.match == "keyword":
            return bool(re.search(rule.value, text, re.IGNORECASE))
        if rule.match == "sensitive":
            low = text.lower()
            return any(word in low for word in self.sensitive_words)
        return False

    def record(self, decision: Decision, objective: str, scenario: str = "") -> dict[str, Any]:
        entry = {
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scenario": scenario,
            "objective": objective[:160],
            "target": decision.target.id,
            "label": decision.target.label,
            "model": decision.target.model,
            "reason": decision.reason,
            "matched": decision.matched,
        }
        self.history.append(entry)
        self.history = self.history[-50:]
        return entry

    # ---------- édition ----------
    def upsert_target(self, target: Target) -> None:
        target.validate()
        for index, existing in enumerate(self.targets):
            if existing.id == target.id:
                self.targets[index] = target
                return
        self.targets.append(target)

    def remove_target(self, target_id: str) -> None:
        if len(self.targets) <= 1:
            raise RoutingError("une politique a besoin d'au moins une cible")
        if any(rule.target == target_id for rule in self.rules):
            raise RoutingError(f"la cible {target_id} est utilisée par une règle, retire la règle d'abord")
        self.targets = [target for target in self.targets if target.id != target_id]
        if self.default_target == target_id:
            self.default_target = self.targets[0].id if self.targets else ""
        if self.override == target_id:
            self.override = ""

    def set_rules(self, rules: list[Rule]) -> None:
        ids = {target.id for target in self.targets}
        for rule in rules:
            rule.validate(ids)
        self.rules = rules
