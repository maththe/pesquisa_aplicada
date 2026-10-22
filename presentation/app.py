"""Servidor local da interface de apresentacao do caso de uso."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
HTML = Path(__file__).with_name("docker.html")
ACTION_LOCK = threading.Lock()


def compose(*args: str, env_overrides: dict[str, str] | None = None) -> None:
    environment = os.environ.copy()
    if env_overrides:
        environment.update(env_overrides)
    result = subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        capture_output=True,
        env=environment,
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


def configure_users_overload(limit: int, delay_ms: int) -> None:
    compose(
        "up",
        "-d",
        "--force-recreate",
        "--no-deps",
        "users-service",
        env_overrides={
            "USERS_OVERLOAD_CONCURRENCY_LIMIT": str(limit),
            "USERS_OVERLOAD_DELAY_MS": str(delay_ms),
        },
    )
    wait_for_users()


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
    if not expected:
        title = "Verificar estado dos serviços"
        summary = (
            "As respostas observadas não confirmam o cenário esperado. "
            "Confira os resultados HTTP e o diagnóstico antes de continuar."
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
                    "message": data.get("message"),
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
    priorities = {
        "overload_rejected": 0,
        "dependency_http_error": 1,
        "dependency_unavailable": 1,
        "dependency_timeout": 1,
        "request_completed": 2,
    }
    compact.sort(key=lambda item: priorities.get(item.get("event", ""), 3))
    return compact[:12]


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


def with_ai_diagnosis(observation: dict[str, Any], start: str) -> dict[str, Any]:
    try:
        return add_ai_diagnosis(observation, start)
    except Exception as exc:
        print(f"Diagnosis unavailable: {type(exc).__name__}", flush=True)
        observation["ai_error"] = (
            "Diagnóstico indisponível. Verifique coleta, banco e configuração da LLM no backend."
        )
        return observation


def run_overload_action() -> dict[str, Any]:
    # Mantém a cadeia causal completa dentro da janela máxima de 80 evidências:
    # cada falha produz logs em Users, Orders e Gateway.
    total_requests = 12
    concurrency = 12
    configured_limit = 3
    delay_ms = 350
    configure_users_overload(configured_limit, delay_ms)
    compose("stop", "collector")
    start = datetime.now(UTC).isoformat()
    correlation = f"web-load-{uuid4()}"
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            responses = list(
                executor.map(
                    lambda _: request("http://127.0.0.1:8000/orders/1", correlation),
                    range(total_requests),
                )
            )
        failures = [response for response in responses if response["status"] != 200]
        representative = failures[0] if failures else responses[0]
        gateway = request("http://127.0.0.1:8000/health")
        orders = request("http://127.0.0.1:8002/health")
        users = request("http://127.0.0.1:8001/health")
        observation = {
            "scenario": "overload",
            "ok": bool(failures) and gateway["status"] == 200 and orders["status"] == 200,
            "title": "Sobrecarga derrubou a operação",
            "summary": (
                f"Uma rajada de {total_requests} consultas concorrentes excedeu o limite "
                f"experimental de {configured_limit} em Users. {len(failures)} consultas "
                "falharam, embora os health checks locais continuassem respondendo."
            ),
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "request_id": correlation,
            "load": {
                "total_requests": total_requests,
                "concurrency": concurrency,
                "configured_limit": configured_limit,
                "delay_ms": delay_ms,
                "failed_requests": len(failures),
                "successful_requests": total_requests - len(failures),
            },
            "checks": {
                "gateway": gateway,
                "orders": orders,
                "users": users,
                "order": representative,
            },
        }
        return with_ai_diagnosis(observation, start)
    finally:
        configure_users_overload(0, 0)
        compose("start", "collector")


def run_action(action: str) -> dict[str, Any]:
    with ACTION_LOCK:
        if action == "overload":
            return run_overload_action()
        if action in ("normal", "recover"):
            configure_users_overload(0, 0)
        elif action == "failure":
            configure_users_overload(0, 0)
            compose("stop", "users-service")
        elif action == "status":
            return observe("status", f"web-status-{uuid4()}")
        else:
            raise ValueError("Ação desconhecida")

        compose("stop", "collector")
        start = datetime.now(UTC).isoformat()
        correlation = f"web-demo-{uuid4()}"
        try:
            return with_ai_diagnosis(observe(action, correlation), start)
        finally:
            compose("start", "collector")


class JobStore:
    """One experiment at a time, with bounded in-memory results."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active: str | None = None

    def submit(self, action: str) -> str | None:
        with self.lock:
            if self.active is not None:
                return None
            while len(self.jobs) >= 20:
                del self.jobs[next(iter(self.jobs))]
            job_id = str(uuid4())
            self.jobs[job_id] = {"id": job_id, "action": action, "state": "running"}
            self.active = job_id
        threading.Thread(target=self.execute, args=(job_id, action), daemon=True).start()
        return job_id

    def execute(self, job_id: str, action: str) -> None:
        try:
            result = run_action(action)
            update = {"state": "completed", "result": result}
        except Exception as exc:
            print(f"Experiment failed: {type(exc).__name__}", flush=True)
            update = {"state": "failed", "error": "O cenário falhou. Consulte os logs do backend."}
        with self.lock:
            self.jobs[job_id].update(update)
            self.active = None

    def read(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None


JOBS = JobStore()


class Handler(BaseHTTPRequestHandler):
    def origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin in self.server.allowed_origins  # type: ignore[attr-defined]

    def authorized(self) -> bool:
        if not self.origin_allowed():
            self.send_json({"error": "Origem não autorizada."}, 403)
            return False
        token = self.server.api_token  # type: ignore[attr-defined]
        if token and not secrets.compare_digest(
            self.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()
        ):
            self.send_json({"error": "Token de acesso inválido ou ausente."}, 401)
            return False
        return True

    def send_json(self, value: Any, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin")
        if origin and self.origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self.origin_allowed():
            self.send_json({"error": "Origem não autorizada."}, 403)
            return
        self.send_response(204)
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/":
            payload = HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if not self.authorized():
            return
        if path == "/api/health":
            self.send_json({"status": "ok", "execution": "docker", "api_version": 1})
        elif path.startswith("/api/jobs/"):
            job = JOBS.read(path.removeprefix("/api/jobs/"))
            self.send_json(
                job or {"error": "Execução não encontrada; o backend pode ter reiniciado."},
                200 if job else 404,
            )
        else:
            self.send_json({"error": "Rota não encontrada."}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self.authorized():
            return
        action = urlsplit(self.path).path.removeprefix("/api/")
        if action not in {"normal", "failure", "recover", "overload", "status"}:
            self.send_json({"error": "Ação desconhecida."}, 404)
            return
        job_id = JOBS.submit(action)
        if job_id is None:
            self.send_json(
                {"error": "Já existe um cenário em execução. Aguarde sua conclusão."}, 409
            )
            return
        self.send_json({"id": job_id, "state": "running"}, 202)

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_server(host: str, port: int) -> ThreadingHTTPServer:
    token = os.environ.get("PRESENTATION_API_TOKEN", "")
    if host not in {"127.0.0.1", "localhost", "::1"} and len(token) < 32:
        raise ValueError("Acesso remoto exige PRESENTATION_API_TOKEN com ao menos 32 caracteres")
    server = ThreadingHTTPServer((host, port), Handler)
    server.api_token = token  # type: ignore[attr-defined]
    origins = {
        item.strip().rstrip("/")
        for item in os.environ.get("PRESENTATION_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    }
    if "*" in origins:
        server.server_close()
        raise ValueError("Configure origens exatas; wildcard não é permitido")
    origins.update(
        {f"http://127.0.0.1:{server.server_port}", f"http://localhost:{server.server_port}"}
    )
    server.allowed_origins = origins  # type: ignore[attr-defined]
    return server


def main() -> None:
    host = os.environ.get("PRESENTATION_HOST", "127.0.0.1")
    port = int(os.environ.get("PRESENTATION_PORT", "8090"))
    server = create_server(host, port)
    print(f"Apresentação iniciada na porta {port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        # Wait for any scenario before the existing recovery commands.
        with ACTION_LOCK:
            configure_users_overload(0, 0)
            compose("start", "collector")
        server.server_close()


if __name__ == "__main__":
    main()
