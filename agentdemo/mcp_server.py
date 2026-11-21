"""Serveur MCP minimal : les outils de Vigie exposés à un client externe, en JSON-RPC sur stdio.

Choix assumés, écrits ici et dans le README :

* transport stdio, une ligne JSON par message, aucune dépendance ;
* seuls les outils de lecture, d'analyse et de mémoire sont exposés. Les outils de courrier et
  d'accès réseau restent dehors : un client MCP ne doit pas pouvoir envoyer un mail ou sortir des
  données parce qu'il a listé un catalogue ;
* tout s'exécute dans un dossier de travail dédié, avec les mêmes garde-fous de chemin que l'agent.

    python3 -m agentdemo mcp
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .skills import SkillStore
from .tools import Sandbox, ToolError, build_registry

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "vigie", "version": "1.0.0"}

EXPOSED = (
    "fs_list",
    "fs_read",
    "fs_write",
    "fs_move",
    "csv_profile",
    "csv_dir_profile",
    "chart_bar",
    "rss_rank",
    "inputs_list",
    "skill_list",
    "skill_recall",
    "skill_write",
)

TYPE_MAP = {"max_chars": "integer", "top_n": "integer", "limit": "integer", "max_steps": "integer"}


def schema_for(tool: Any) -> dict[str, Any]:
    """Dérive un JSON Schema de la signature déclarée dans le registre (« fs_read(path, max_chars?) »)."""
    signature = tool.signature
    inside = signature[signature.find("(") + 1 : signature.rfind(")")].strip()
    properties: dict[str, Any] = {}
    required: list[str] = []
    for raw in [part.strip() for part in inside.split(",") if part.strip()]:
        optional = raw.endswith("?")
        name = raw.rstrip("?").split("=")[0].strip()
        if not name:
            continue
        kind = TYPE_MAP.get(name, "string")
        properties[name] = {"type": kind} if kind != "string" else {"type": "string"}
        if not optional:
            required.append(name)
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": {"type": "object", "properties": properties, "required": required},
    }


class McpServer:
    def __init__(self, workspace: Path, data_dir: Path) -> None:
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.data_dir = Path(data_dir)
        artifacts: list[str] = []
        self.registry = build_registry(
            Sandbox(self.workspace), artifacts, SkillStore(Path(data_dir) / "skills")
        )
        self.tools = {name: self.registry[name] for name in EXPOSED if name in self.registry}
        # les outils du catalogue installé sont exposés comme les autres, empreinte vérifiée au chargement
        from . import toolcatalog

        for manifest in toolcatalog.installed(self.data_dir):
            try:
                tool = toolcatalog.load_tool(self.data_dir, manifest)
            except toolcatalog.CatalogError:
                continue
            self.tools[tool.name] = tool

    # ---------- protocole ----------
    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        ident = message.get("id")
        params = message.get("params") or {}

        if method == "notifications/initialized":
            return None
        if method == "initialize":
            requested = str(params.get("protocolVersion") or PROTOCOL_VERSION)
            return self._result(
                ident,
                {
                    "protocolVersion": requested if requested in (PROTOCOL_VERSION, "2025-06-18") else PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                },
            )
        if method == "ping":
            return self._result(ident, {})
        if method == "tools/list":
            return self._result(ident, {"tools": [schema_for(tool) for tool in self.tools.values()]})
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return self._error(ident, -32602, "params invalides : arguments doit être un objet")
            if name not in self.tools:
                return self._error(ident, -32602, f"outil inconnu ou non exposé : {name}")
            try:
                text = self.tools[name].fn(**arguments)
            except ToolError as exc:
                return self._result(
                    ident, {"content": [{"type": "text", "text": str(exc)}], "isError": True}
                )
            except TypeError as exc:
                return self._error(ident, -32602, f"arguments invalides pour {name} : {exc}")
            return self._result(ident, {"content": [{"type": "text", "text": str(text)}], "isError": False})
        return self._error(ident, -32601, f"méthode inconnue : {method}")

    @staticmethod
    def _result(ident: Any, payload: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": ident, "result": payload}

    @staticmethod
    def _error(ident: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


def serve_stdio(workspace: Path, data_dir: Path) -> None:
    """Boucle principale : une requête par ligne, une réponse par ligne, rien d'autre sur stdout."""
    server = McpServer(workspace, data_dir)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON invalide"}}), flush=True)
            continue
        if not isinstance(message, dict):
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "requête invalide"}}), flush=True)
            continue
        response = server.handle(message)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
