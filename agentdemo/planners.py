"""Planner backends: how the agent decides its next move.

Two backends are provided:

* ``ReplayPlanner``, replays a recorded decision trace. Deterministic, no model,
  no API key, no network. Tool calls are still executed for real.
* ``OpenAICompatPlanner``, calls any OpenAI-compatible ``/chat/completions``
  endpoint (Ollama, LM Studio, vLLM, or a hosted API) with the tool catalogue in
  the system prompt, and expects a single JSON action back.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Protocol


def normalize_base_url(url: str) -> str:
    """Complète un endpoint nu (`http://hote:port`) en `…/v1`.

    LM Studio, Ollama et vLLM exposent l'API compatible OpenAI sous `/v1`. Sans ce
    suffixe, le serveur répond « endpoint inconnu » avec un 200 sans `choices`,
    ce qui ressemble à une panne de modèle alors que c'est juste une URL courte.
    """
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        return cleaned
    without_scheme = cleaned.split("://", 1)[-1]
    path = without_scheme.split("/", 1)[1] if "/" in without_scheme else ""
    if path:
        return cleaned
    return f"{cleaned}/v1"


class Planner(Protocol):
    label: str

    def next_action(self, objective: str, history: list[dict[str, Any]]) -> dict[str, Any]: ...


class ReplayPlanner:
    """Deterministic planner: replays a recorded trace, one step per call."""

    def __init__(self, trace: list[dict[str, Any]]) -> None:
        self.trace = list(trace)
        self.cursor = 0
        self.label = "replay"

    def child(self) -> "ReplayPlanner | None":
        """Un replay n'a pas de successeur : le sous-agent doit avoir sa propre cassette."""
        return None

    def skip(self, steps: int) -> None:
        """Reprise : la cassette reprend là où le run s'est arrêté."""
        self.cursor = max(self.cursor, min(int(steps), len(self.trace)))

    def next_action(self, objective: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        if self.cursor >= len(self.trace):
            return {"thought": "Trace épuisée.", "final": "Scénario terminé."}
        action = dict(self.trace[self.cursor])
        self.cursor += 1
        return action


class FallbackPlanner:
    """Essaie les backends dans l'ordre : le premier qui répond parle.

    Un seul passage par étape, et seulement sur une erreur de transport. Une réponse illisible
    (JSON invalide, mauvais format) n'est pas un incident de backend : la relancer ailleurs
    masquerait la vraie erreur.
    """

    def __init__(self, chain: list[tuple[str, "Planner"]], on_event=None) -> None:
        self._chain = list(chain)
        self._on_event = on_event
        self.label = "fallback:" + ",".join(label for label, _ in self._chain)

    @property
    def tools(self):
        return getattr(self._chain[0][1], "tools", None) if self._chain else None

    @tools.setter
    def tools(self, value):
        for _, planner in self._chain:
            if hasattr(planner, "tools"):
                planner.tools = value

    def child(self) -> "FallbackPlanner | None":
        children = []
        for label, planner in self._chain:
            child = planner.child() if hasattr(planner, "child") else None
            if child is not None:
                children.append((label, child))
        return FallbackPlanner(children, self._on_event) if children else None

    def next_action(self, objective: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        last: Exception | None = None
        for index, (label, planner) in enumerate(self._chain):
            try:
                return planner.next_action(objective, history)
            except RuntimeError as exc:
                last = exc
                if index + 1 < len(self._chain) and self._on_event:
                    self._on_event(
                        {
                            "event": "fallback",
                            "from": label,
                            "to": self._chain[index + 1][0],
                            "reason": str(exc)[:200],
                        }
                    )
        raise RuntimeError(str(last) if last else "aucun backend disponible")


class OpenAICompatPlanner:
    """Live planner against an OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        tools: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> None:
        raw_base = base_url or os.environ.get("AGENTDEMO_LLM_BASE_URL", "http://localhost:11434/v1")
        self.base_url = normalize_base_url(raw_base)
        self.model = model or os.environ.get("AGENTDEMO_LLM_MODEL", "qwen2.5-coder:7b")
        self.api_key = api_key or os.environ.get("AGENTDEMO_LLM_API_KEY", "")
        self.timeout = timeout
        self.tools = tools or {}
        self.label = f"live:{self.model}"

    def child(self) -> "OpenAICompatPlanner":
        """Un sous-agent : même endpoint, même modèle, catalogue rempli par son propre run."""
        return OpenAICompatPlanner(
            base_url=self.base_url,
            model=self.model,
            api_key=self.api_key,
            timeout=self.timeout,
        )

    def _post_with_retry(self, request: urllib.request.Request, attempts: int = 2) -> dict[str, Any]:
        """Un incident passager de l'endpoint ne doit pas tuer un run entier.

        Les serveurs locaux renvoient parfois `HTTP 400 {"error":"terminated"}` quand un modèle sature
        son contexte, et les passerelles distantes des 502. On retente une fois, puis on remonte
        l'erreur telle quelle : un échec réel doit rester lisible.
        """
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    return json.loads(response.read().decode())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                last = RuntimeError(
                    f"appel modèle impossible ({self.base_url}, modèle {self.model}) : HTTP {exc.code} — {detail}"
                )
                transient = exc.code >= 500 or "terminated" in detail.lower() or exc.code == 429
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = RuntimeError(f"appel modèle impossible ({self.base_url}) : {exc}")
                transient = True
            if not transient or attempt == attempts - 1:
                raise last
            time.sleep(1.5)
        raise last  # pragma: no cover - boucle épuisée

    def next_action(self, objective: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        messages = [{"role": "system", "content": self._system_prompt()}]
        messages.append({"role": "user", "content": f"Objectif : {objective}"})
        for step in history:
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {"thought": step["thought"], "tool": step.get("tool"), "args": step.get("args", {})},
                        ensure_ascii=False,
                    ),
                }
            )
            messages.append({"role": "user", "content": f"Observation : {step.get('observation', '')}"})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Produis UN SEUL objet JSON, sans texte autour : "
                    '{"thought": "...", "tool": "<nom>", "args": {...}} '
                    'ou {"thought": "...", "final": "<bilan>"} quand l\'objectif est atteint.'
                ),
            }
        )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        body = self._post_with_retry(request)
        if "choices" not in body:
            excerpt = json.dumps(body, ensure_ascii=False)[:300]
            raise RuntimeError(
                f"réponse inattendue de {self.base_url} (pas de 'choices') : {excerpt}, "
                "vérifie que l'endpoint est bien l'API compatible OpenAI, en général …/v1"
            )
        text = body["choices"][0]["message"]["content"]
        if os.environ.get("AGENTDEMO_DEBUG_RAW"):
            # utile quand un petit modèle répond à côté : on garde la réponse brute
            from pathlib import Path as _Path

            log = _Path(os.environ["AGENTDEMO_DEBUG_RAW"])
            with log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"len": len(text), "text": text}, ensure_ascii=False) + "\n")
        action = _extract_json(text)
        if action is None:
            return {
                "thought": "Réponse du modèle non exploitable, arrêt propre du run.",
                "final": text[:600],
            }
        return action

    def _system_prompt(self) -> str:
        lines = [
            "Tu es un agent autonome. Tu reçois un objectif, tu choisis des outils,",
            "tu enchaînes les étapes et tu produis un livrable vérifiable.",
            "Tu écris tous tes fichiers dans le bac à sable du run, jamais ailleurs.",
            "",
            "Outils disponibles :",
        ]
        for tool in self.tools.values():
            lines.append(f"- {tool.signature}, {tool.description}")
        lines += [
            "",
            "Règles :",
            "- une seule action par tour, JSON strict, pas de balises de code ;",
            "- commence par fs_list('.') : ne devine jamais un chemin, ils sont affichés ;",
            "- la clé args est toujours un objet JSON, jamais une chaîne ;",
            "- si le catalogue contient skill_recall, commence par le consulter : une procédure",
            "  déjà apprise évite de refaire une erreur coûteuse ;",
            "- quand une étape échoue ou qu'une découverte te coûte du temps, écris la leçon",
            "  avec skill_write : elle sera relue au prochain run ;",
            "- quand le livrable est écrit et relu, réponds avec la clé 'final'.",
        ]
        return "\n".join(lines)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Premier objet JSON complet de la réponse.

    Les petits modèles enchaînent parfois deux objets (l'appel d'outil puis un `final`).
    Découper du premier `{` au dernier `}` donnait alors un JSON invalide, l'appel d'outil
    était perdu et le run se terminait sans livrable : on lit donc objet par objet.
    """
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()

    for candidate in _json_objects(text):
        for attempt in (candidate, _escape_control_chars(candidate)):
            try:
                parsed = json.loads(attempt, strict=False)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _json_objects(text: str) -> list[str]:
    """Découpe le texte en objets JSON de premier niveau, équilibrés et hors chaînes."""
    objects: list[str] = []
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
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                objects.append(text[start : index + 1])
                start = -1
    return objects


def _escape_control_chars(text: str) -> str:
    """Échappe les retours à la ligne bruts à l'intérieur des chaînes JSON.

    Les petits modèles écrivent un contenu multi-ligne sans `\\n` : le JSON est invalide,
    l'appel d'outil est perdu et le run se termine sans livrable. On répare au lieu de perdre.
    """
    out: list[str] = []
    inside = False
    escaped = False
    for char in text:
        if inside:
            if escaped:
                out.append(char)
                escaped = False
                continue
            if char == "\\":
                out.append(char)
                escaped = True
                continue
            if char == '"':
                inside = False
                out.append(char)
                continue
            if char in "\n\r\t":
                out.append("\\n" if char == "\n" else ("\\r" if char == "\r" else "\\t"))
                continue
            out.append(char)
        else:
            if char == '"':
                inside = True
            out.append(char)
    return "".join(out)
