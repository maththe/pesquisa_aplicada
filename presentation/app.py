"""Servidor local da interface de apresentacao do caso de uso."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
HTML = Path(__file__).with_name("index.html")
ACTION_LOCK = threading.Lock()


def compose(*args: str) -> None:
    result = subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        message = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "erro"
        raise RuntimeError(f"Docker Compose: {message}")


def diagnostics(*args: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "compose", "run", "--rm", "--no-deps", "-T", "diagnostics", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    try:
        payload: dict[str, Any] = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError("A CLI de diagnóstico não retornou JSON válido") from exc
    if result.returncode and payload.get("response", {}).get("outcome") != "failure":
        raise RuntimeError("A CLI de diagnóstico falhou")
    return payload


def request(url: str, request_id: str | None = None) -> dict[str, Any]:
    headers = {"X-Request-ID": request_id} if request_id else {}
    started = time.perf_counter()
    try:
        with urlopen(Request(url, headers=headers), timeout=8) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        status = exc.code
    except (URLError, TimeoutError):
        return {"status": None, "body": None, "elapsed_ms": None, "reachable": False}
    try:
        parsed: Any = json.loads(body)
    except ValueError:
        parsed = body
    return {
        "status": status,
        "body": parsed,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "reachable": True,
    }


def wait_for_users() -> None:
    for _ in range(30):
        if request("http://127.0.0.1:8000/users/1")["status"] == 200:
            return
        time.sleep(0.5)
    raise RuntimeError("Users não ficou disponível")


def observe(scenario: str, correlation: str) -> dict[str, Any]:
    gateway = request("http://127.0.0.1:8000/health")
    orders = request("http://127.0.0.1:8002/health")
    users = request("http://127.0.0.1:8001/health")
    order = request("http://127.0.0.1:8000/orders/1", correlation)

    is_incident = scenario == "failure"
    expected = (
        gateway["status"] == 200
        and orders["status"] == 200
        and (
            (is_incident and users["status"] is None and order["status"] in (503, 504))
            or (not is_incident and users["status"] == 200 and order["status"] == 200)
        )
    )
    if is_incident:
        title = "Incidente confirmado"
        summary = (
            "O Gateway e Orders continuam saudáveis, mas o pedido falha porque "
            "Users está indisponível. O erro percebido na entrada vem de uma dependência."
        )
    else:
        title = "Fluxo funcionando"
        summary = (
            "A consulta percorreu Gateway, Orders e Users com sucesso. "
            "A operação do cliente respondeu HTTP 200."
        )
    return {
        "scenario": scenario,
        "ok": expected,
        "title": title,
        "summary": summary,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "request_id": correlation,
        "checks": {
            "gateway": gateway,
            "orders": orders,
            "users": users,
            "order": order,
        },
    }


def compact_evidence(run: dict[str, Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in run["context"]["evidence"]:
        data = item["data"]
        if item["kind"] == "log":
            compact.append(
                {
                    "id": item["evidence_id"],
                    "kind": "log",
                    "service": data.get("service"),
                    "event": data.get("event"),
                    "dependency": data.get("dependency"),
                    "status": data.get("status_code"),
                    "error": data.get("error_type"),
                }
            )
        else:
            states = [
                {
                    "service": service["service"],
                    "reachable": service["reachable"],
                    "status": service["status_code"],
                    "error": service["error_type"],
                }
                for service in data.get("services", [])
            ]
            compact.append(
                {
                    "id": item["evidence_id"],
                    "kind": "snapshot",
                    "states": states,
                }
            )
    return compact


def add_ai_diagnosis(observation: dict[str, Any], start: str) -> dict[str, Any]:
    diagnostics("collect", "--once")
    end = datetime.now(UTC).isoformat()
    run = diagnostics(
        "diagnose",
        "--start",
        start,
        "--end",
        end,
        "--service",
        "gateway",
        "--request-id",
        observation["request_id"],
    )
    response = run["response"]
    execution = run["executions"][-1]
    observation["ai"] = {
        "run_id": run["run_id"],
        "outcome": response["outcome"],
        "summary": response["summary"],
        "hypotheses": response["hypotheses"],
        "recommendations": response["recommendations"],
        "limitations": response["limitations"],
        "evidence_ids": response["evidence_ids"],
        "evidence": compact_evidence(run),
        "model": execution["model"],
        "provider": execution["provider"],
        "simulated": run["simulated"],
        "duration_ms": round(execution["duration_ms"], 2),
    }
    return observation


def run_action(action: str) -> dict[str, Any]:
    with ACTION_LOCK:
        if action in ("normal", "recover"):
            compose("start", "users-service")
            wait_for_users()
        elif action == "failure":
            compose("stop", "users-service")
        elif action == "status":
            return observe("status", f"web-status-{uuid4()}")
        else:
            raise ValueError("Ação desconhecida")

        compose("stop", "collector")
        start = datetime.now(UTC).isoformat()
        correlation = f"web-demo-{uuid4()}"
        try:
            return add_ai_diagnosis(observe(action, correlation), start)
        finally:
            compose("start", "collector")


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value: Any, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
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
        if self.path == "/api/status":
            try:
                self.send_json(run_action("status"))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        action = self.path.removeprefix("/api/")
        if action not in {"normal", "failure", "recover"}:
            self.send_error(404)
            return
        try:
            self.send_json(run_action(action))
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
        compose("start", "users-service", "collector")
        server.server_close()


if __name__ == "__main__":
    main()
