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

    def next_action(self, objective: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        if self.cursor >= len(self.trace):
            return {"thought": "Trace épuisée.", "final": "Scénario terminé."}
        action = dict(self.trace[self.cursor])
        self.cursor += 1
        return action


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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"appel modèle impossible ({self.base_url}) : {exc}") from exc
        if "choices" not in body:
            excerpt = json.dumps(body, ensure_ascii=False)[:300]
            raise RuntimeError(
                f"réponse inattendue de {self.base_url} (pas de 'choices') : {excerpt}, "
                "vérifie que l'endpoint est bien l'API compatible OpenAI, en général …/v1"
            )
        text = body["choices"][0]["message"]["content"]
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
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
