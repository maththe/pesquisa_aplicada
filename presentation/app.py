"""Servidor local da interface de apresentação do caso de uso."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.scenarios import SCENARIOS, Lab, observe  # noqa: E402

HTML = Path(__file__).with_name("index.html")
ACTION_LOCK = threading.Lock()
LAB = Lab()


def status() -> dict[str, Any]:
    """Leitura rápida, sem alterar o ambiente nem chamar a IA."""
    correlation = f"status-{uuid4().hex[:12]}"
    scenario = SCENARIOS["normal"]
    responses = LAB.drive(scenario, correlation)[:1]
    return observe(scenario, correlation, responses, LAB.health())


def run_action(action: str, automatic: bool = False) -> dict[str, Any]:
    if action not in SCENARIOS:
        raise ValueError("Ação desconhecida")
    with ACTION_LOCK:
        return LAB.execute_auto(action) if automatic else LAB.execute(action)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value: Any, status_code: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            payload = HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/api/scenarios":
            self.send_json(
                [
                    {
                        "key": scenario.key,
                        "title": scenario.title,
                        "description": scenario.description,
                    }
                    for scenario in SCENARIOS.values()
                ]
            )
            return
        if self.path == "/api/status":
            try:
                self.send_json(status())
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.removeprefix("/api/")
        automatic = path.startswith("auto/")
        action = path.removeprefix("auto/")
        if action not in SCENARIOS:
            self.send_error(404)
            return
        try:
            self.send_json(run_action(action, automatic))
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8090), Handler)
    print("Apresentacao: http://127.0.0.1:8090", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        LAB.reset()
        LAB.compose("start", "collector")
        server.server_close()


if __name__ == "__main__":
    main()
