"""Endpoint compatible OpenAI, simulé, pour tester le banc de mesure sans modèle.

Ce n'est **pas** un modèle : il renvoie une réponse construite à partir de la question
(en écho), avec une latence et un nombre de tokens de sortie configurables. Il sert à :

- valider le câblage du banc (`bench/bench.py`) en CI, sans GPU ni clé ;
- produire un rapport de démonstration quand aucun modèle n'est disponible.

Les chiffres qu'il produit ne mesurent **rien** d'utile : ne les citez jamais comme des
mesures de modèle.

    python3 bench/fake_endpoint.py --port 8077 --delay 0.35 --tokens 90
"""

from __future__ import annotations

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG = {"delay": 0.3, "tokens": 80, "model": "modele-simule-8b"}


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-endpoint/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A002  # silence
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/healthz", ""):
            return self._json({"ok": True})
        if self.path.rstrip("/").endswith("/models"):
            return self._json({"data": [{"id": CONFIG["model"], "object": "model"}]})
        return self._json({"error": "route inconnue"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "json invalide"}, 400)
        question = ""
        for message in reversed(payload.get("messages", [])):
            if message.get("role") == "user":
                question = message.get("content", "")
                break

        time.sleep(CONFIG["delay"])
        answer = self._answer(question)
        completion_tokens = max(1, len(answer.split()) if answer else CONFIG["tokens"])
        self._json(
            {
                "id": "chatcmpl-simule",
                "object": "chat.completion",
                "model": payload.get("model") or CONFIG["model"],
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}
                ],
                "usage": {
                    "prompt_tokens": len(question.split()),
                    "completion_tokens": completion_tokens,
                    "total_tokens": len(question.split()) + completion_tokens,
                },
            }
        )

    def _answer(self, question: str) -> str:
        """Réponse bête mais déterministe : premiers nombres/mots de la question."""
        numbers = re.findall(r"\d[\d/.,:T-]*", question)
        if "un seul mot" in question:
            choices = re.findall(r"urgent|administratif|info|indesirable", question)
            return choices[0] if choices else "info"
        if "oui ou non" in question:
            return "oui"
        if "AAAA-MM-JJ" in question:
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", question)
            return max(dates) if dates else "1970-01-01"
        if numbers:
            return numbers[0]
        return "réponse simulée"

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Endpoint OpenAI simulé pour le banc de mesure")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8077)
    parser.add_argument("--delay", type=float, default=0.3, help="latence simulée en secondes")
    parser.add_argument("--tokens", type=int, default=80)
    parser.add_argument("--model", default="modele-simule-8b")
    args = parser.parse_args()
    CONFIG.update(delay=args.delay, tokens=args.tokens, model=args.model)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"endpoint simulé sur http://{args.host}:{args.port}/v1 (latence {args.delay}s)")
    server.serve_forever()


if __name__ == "__main__":
    main()
