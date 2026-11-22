"""Revue d'un livrable par un second modèle avant de conclure.

Le principe est celui d'une relecture en binôme : celui qui a écrit n'est pas celui qui valide. Le
relecteur ne réécrit rien, il juge et motive. Un verdict `rejette` renvoie ses motifs au rédacteur,
qui corrige et repasse. Deux rejets suffisent : au-delà, on s'arrête au lieu de brûler le budget.

Deux implémentations derrière la même méthode `review(objective, artifacts, history)` :

* `ReplayReviewer` lit des verdicts enregistrés : la démonstration reste déterministe, hors ligne ;
* `ModelReviewer` interroge un vrai modèle, avec un prompt strict et un parsing tolérant.

Le relecteur ne lit que les livrables déclarés, jamais le reste du disque.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MAX_ARTIFACT_CHARS = 4000


class ReviewError(RuntimeError):
    """Revue impossible, avec la raison lisible."""


def _clean(verdict: dict[str, Any]) -> dict[str, Any]:
    """Normalise un verdict : inconnu ou vide vaut rejet, jamais acceptation par défaut."""
    raw = str(verdict.get("verdict") or "").strip().lower()
    if raw in ("accepte", "accepté", "accept", "ok", "valide"):
        decision = "accepte"
    elif raw in ("rejette", "rejeté", "reject", "refuse", "refusé"):
        decision = "rejette"
    else:
        decision = "rejette"
    motifs = [str(item) for item in (verdict.get("motifs") or []) if str(item).strip()]
    corrections = [str(item) for item in (verdict.get("corrections") or []) if str(item).strip()]
    if decision == "rejette" and not motifs:
        motifs = ["verdict inexploitable : le relecteur n'a pas donné de motif"]
    return {"verdict": decision, "motifs": motifs, "corrections": corrections}


class ReplayReviewer:
    """Verdicts enregistrés, rejoués dans l'ordre : aucun réseau, même résultat à chaque fois."""

    label = "review:replay"

    def __init__(self, verdicts: list[dict[str, Any]]) -> None:
        self._verdicts = [dict(item) for item in verdicts]

    @classmethod
    def from_file(cls, path: Path) -> "ReplayReviewer":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ReviewError(f"reviewer.json absent : {path}") from exc
        except json.JSONDecodeError as exc:
            raise ReviewError(f"reviewer.json illisible : {path} — {exc.msg}") from exc
        verdicts = payload if isinstance(payload, list) else payload.get("verdicts") or []
        if not isinstance(verdicts, list):
            raise ReviewError(f"reviewer.json : liste de verdicts attendue dans {path}")
        return cls(verdicts)

    def review(self, objective: str, artifacts: dict[str, str], history: list[dict[str, Any]]) -> dict[str, Any]:
        if not self._verdicts:
            return {"verdict": "accepte", "motifs": [], "corrections": []}
        return _clean(self._verdicts.pop(0))


class ModelReviewer:
    """Un second modèle relit : il ne réécrit pas, il juge avec des motifs."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: int = 120,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.model = model
        self.api_key = api_key or ""
        self.timeout = timeout
        self.label = f"review:{model}"

    def _prompt(self, objective: str, artifacts: dict[str, str]) -> str:
        lines = [
            "Tu es relecteur. Tu ne réécris pas le livrable, tu le juges.",
            f"Objectif confié au rédacteur : {objective}",
            "",
            "Livrables à relire :",
        ]
        for name, content in artifacts.items():
            lines.append(f"--- {name} ---")
            lines.append(content[:MAX_ARTIFACT_CHARS])
        lines += [
            "",
            "Réponds UNIQUEMENT par un objet JSON, sans texte autour :",
            '{"verdict": "accepte" ou "rejette", "motifs": ["..."], "corrections": ["..."]}',
            "Rejette si le livrable ne répond pas à l'objectif, s'il manque une information demandée,",
            "ou s'il affirme un fait que le contenu ne soutient pas.",
        ]
        return "\n".join(lines)

    def review(self, objective: str, artifacts: dict[str, str], history: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "Tu es un relecteur strict. Une seule réponse : un objet JSON."},
                {"role": "user", "content": self._prompt(objective, artifacts)},
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            raise ReviewError(f"relecteur indisponible ({self.base_url}) : HTTP {exc.code} — {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ReviewError(f"relecteur indisponible ({self.base_url}) : {exc}") from exc
        if "choices" not in body:
            raise ReviewError(f"réponse inattendue du relecteur : {json.dumps(body, ensure_ascii=False)[:200]}")
        text = body["choices"][0]["message"]["content"]
        verdict = _first_json(text)
        if verdict is None:
            return {
                "verdict": "rejette",
                "motifs": ["le relecteur n'a pas répondu au format demandé"],
                "corrections": [],
            }
        return _clean(verdict)


def _first_json(text: str) -> dict[str, Any] | None:
    """Premier objet JSON équilibré : les petits modèles encadrent souvent leur réponse de texte."""
    depth = 0
    start = -1
    inside = False
    escaped = False
    for index, char in enumerate(text):
        if inside:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                inside = False
            continue
        if char == '"' and depth > 0:
            inside = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    parsed = json.loads(text[start : index + 1], strict=False)
                except json.JSONDecodeError:
                    start = -1
                    continue
                if isinstance(parsed, dict):
                    return parsed
                start = -1
    return None
