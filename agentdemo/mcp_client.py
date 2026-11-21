"""Client MCP minimal : parler à un serveur pour vérifier qu'il répond.

Un serveur déclaré dans l'interface n'est utile que s'il démarre et expose des outils. Ce module
lance la commande en sous-processus, fait la poignée de main JSON-RPC sur stdio, demande la liste
des outils, puis referme. Rien n'est installé, rien n'est téléchargé : on constate.

    python3 -m agentdemo mcp-servers test --name vigie

Les mêmes garde-fous que le reste : une commande vide est refusée, un délai court évite de bloquer
le serveur web, et une erreur de démarrage est rendue telle quelle au lieu d'être masquée.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 12


class McpClientError(RuntimeError):
    """Le serveur n'a pas répondu comme un serveur MCP."""


def _send(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    process.stdin.flush()


def _read(process: subprocess.Popen[str]) -> dict[str, Any] | None:
    assert process.stdout is not None
    while True:
        line = process.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue


def _close(process: subprocess.Popen[str]) -> None:
    """Ferme le serveur et ses tuyaux : sans ça, le serveur web garde des descripteurs ouverts."""
    try:
        process.terminate()
        process.wait(timeout=3)
    except Exception:  # le serveur refuse de mourir : on ne bloque pas la requête
        process.kill()
    for stream in (process.stdin, process.stdout, process.stderr):
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass


def probe(command: str, args: list[str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Démarre le serveur, liste ses outils, et rend un compte rendu vérifiable."""
    args = list(args or [])
    if not command:
        raise McpClientError("commande vide : rien à lancer")
    executable = shutil.which(command)
    if executable is None:
        raise McpClientError(f"commande introuvable dans l'image : {command}")

    process = subprocess.Popen(  # noqa: S603 - commande déclarée par l'opérateur, pas par le modèle
        [executable, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "vigie-doctor", "version": "1.0.0"},
                },
            },
        )
        reply = _read(process)
        if reply is None:
            raise McpClientError("le serveur s'est arrêté avant la poignée de main")
        if "error" in reply:
            raise McpClientError(f"initialize refusé : {reply['error'].get('message', reply['error'])}")
        server = (reply.get("result") or {}).get("serverInfo") or {}

        _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listing = _read(process)
        if listing is None:
            raise McpClientError("aucune réponse à tools/list")
        if "error" in listing:
            raise McpClientError(f"tools/list refusé : {listing['error'].get('message', listing['error'])}")
        tools = [
            {"name": str(tool.get("name")), "description": str(tool.get("description") or "")[:120]}
            for tool in ((listing.get("result") or {}).get("tools") or [])
        ]
        return {
            "ok": True,
            "server": {"name": server.get("name", ""), "version": server.get("version", "")},
            "protocol": (reply.get("result") or {}).get("protocolVersion", ""),
            "tools": tools,
            "count": len(tools),
        }
    finally:
        _close(process)


def call_tool(
    command: str,
    args: list[str] | None,
    tool: str,
    arguments: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Appelle un outil du serveur, comme le ferait un client MCP."""
    args = list(args or [])
    executable = shutil.which(command)
    if executable is None:
        raise McpClientError(f"commande introuvable dans l'image : {command}")
    process = subprocess.Popen(  # noqa: S603
        [executable, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "vigie-doctor", "version": "1.0.0"},
                },
            },
        )
        if _read(process) is None:
            raise McpClientError("le serveur s'est arrêté avant la poignée de main")
        _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments or {}},
            },
        )
        reply = _read(process)
        if reply is None:
            raise McpClientError(f"aucune réponse à l'appel de {tool}")
        if "error" in reply:
            raise McpClientError(f"appel refusé : {reply['error'].get('message', reply['error'])}")
        result = reply.get("result") or {}
        contents = result.get("content") or []
        text = "\n".join(str(item.get("text", "")) for item in contents if isinstance(item, dict))
        return {"ok": True, "tool": tool, "text": text[:2000], "is_error": bool(result.get("isError"))}
    finally:
        _close(process)
