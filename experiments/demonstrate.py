"""Cenário reprodutível: sucesso -> indisponibilidade de Users -> recuperação."""

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


class Demonstration:
    def __init__(
        self,
        project: str | None,
        port: str,
        output: Path,
        *,
        interactive: bool = False,
        samples: int = 3,
    ) -> None:
        self.compose = ["docker", "compose"]
        if project:
            self.compose += ["--project-name", project]
        self.port = port
        self.output = output
        self.interactive = interactive
        if not 1 <= samples <= 10:
            raise ValueError("samples deve estar entre 1 e 10")
        self.samples = samples

    def present(self, message: str) -> None:
        print(f"\n{message}", flush=True)
        if self.interactive:
            input("Pressione Enter para executar esta etapa: ")

    def observe_operation(self, label: str) -> dict[str, Any]:
        """Consultas sequenciais de negócio; não representa um teste de carga."""
        observations: list[dict[str, Any]] = []
        with httpx.Client(timeout=10, trust_env=False) as client:
            health = client.get(f"http://127.0.0.1:{self.port}/health")
            for _ in range(self.samples):
                correlation = f"sample-{uuid4()}"
                started = perf_counter()
                response = client.get(
                    f"http://127.0.0.1:{self.port}/orders/1",
                    headers={"X-Request-ID": correlation},
                )
                observations.append(
                    {
                        "request_id": correlation,
                        "http_status": response.status_code,
                        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                    }
                )
        failed = sum(item["http_status"] != 200 for item in observations)
        result = {
            "gateway_health_status": health.status_code,
            "sample_count": len(observations),
            "failed_queries": failed,
            "failure_rate_percent": round(failed / len(observations) * 100, 2),
            "mean_elapsed_ms": round(
                sum(item["elapsed_ms"] for item in observations) / len(observations), 2
            ),
            "queries": observations,
            "scope": "Amostra sequencial desta etapa; não é teste de carga.",
        }
        (self.output / f"{label}-operacao.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"Consulta de pedido: {failed}/{len(observations)} falharam; "
            f"latência média={result['mean_elapsed_ms']} ms; "
            f"health local do Gateway=HTTP {health.status_code}.",
            flush=True,
        )
        return result

    def docker(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [*self.compose, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        if check and result.returncode:
            raise RuntimeError(f"Compose falhou: {' '.join(args[:3])}; {result.stderr[-1500:]}")
        return result

    def cli(self, *args: str) -> Any:
        result = self.docker("run", "--rm", "--no-deps", "-T", "diagnostics", *args, check=False)
        try:
            data = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError(f"CLI sem JSON válido: {result.stderr[-1000:]}") from exc
        if result.returncode:
            if isinstance(data, dict) and data.get("response", {}).get("outcome") == "failure":
                return data  # Preservar resposta inválida na evidência da demonstração.
            raise RuntimeError(f"CLI falhou: {args[0]}")
        return data

    def wait_users(self) -> None:
        # Sondar pelo Gateway verifica também a resolução DNS após reiniciar Users.
        with httpx.Client(timeout=5, trust_env=False) as client:
            for _ in range(30):
                try:
                    if client.get(f"http://127.0.0.1:{self.port}/users/1").status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(1)
        raise RuntimeError("Users não ficou disponível após a recuperação")

    def phase(self, label: str, expected_status: int) -> dict[str, Any]:
        start = datetime.now(UTC).isoformat()
        correlation = f"demo-{uuid4()}"
        with httpx.Client(timeout=10, trust_env=False) as client:
            response = client.get(
                f"http://127.0.0.1:{self.port}/orders/1",
                headers={"X-Request-ID": correlation},
            )
        allowed_status = {503, 504} if expected_status == 503 else {expected_status}
        if response.status_code not in allowed_status:
            raise RuntimeError(
                f"{label}: esperado HTTP {sorted(allowed_status)}, obtido {response.status_code}"
            )
        if response.headers.get("X-Request-ID") != correlation:
            raise RuntimeError("Correlação não preservada")
        operation = self.observe_operation(label)
        if operation["gateway_health_status"] != 200:
            raise RuntimeError("Health local do Gateway não respondeu HTTP 200")
        if any(item["http_status"] not in allowed_status for item in operation["queries"]):
            raise RuntimeError(f"{label}: consultas adicionais divergiram do cenário esperado")
        collected = self.cli("collect", "--once")
        current = self.cli("current")
        if current["snapshot_id"] != collected["snapshot_id"]:
            raise RuntimeError("Snapshot no etcd diverge da coleta")
        end = datetime.now(UTC).isoformat()
        run = self.cli(
            "diagnose",
            "--start",
            start,
            "--end",
            end,
            "--service",
            "gateway",
            "--request-id",
            correlation,
        )
        items = run["context"]["evidence"]
        logs = [item for item in items if item["kind"] == "log"]
        if not logs or any(item["data"]["request_id"] != correlation for item in logs):
            raise RuntimeError("Evidências sem correlação correta")
        expected_services = {"gateway", "orders-service"}
        if expected_status == 200:
            expected_services.add("users-service")
        if not expected_services <= {item["data"]["service"] for item in logs}:
            raise RuntimeError("Logs esperados não foram encontrados")
        if expected_status == 503 and not any(
            item["data"]["event"] in ("dependency_unavailable", "dependency_timeout")
            and item["data"]["dependency"] == "users-service"
            for item in logs
        ):
            raise RuntimeError("Falta evidência de indisponibilidade de Users")
        # Cada referência pode ser resolvida para a evidência original persistida.
        for item in items:
            stored = self.cli("evidence", item["evidence_id"])
            if stored["data"] != item["data"]:
                raise RuntimeError("Evidência no contexto difere do histórico")
        restored = self.cli("run", run["run_id"])
        if restored != run:
            raise RuntimeError("Execução não persistida corretamente")
        result = {
            "phase": label,
            "http_status": response.status_code,
            "request_id": correlation,
            "operation": operation,
            "window": {"start": start, "end": end},
            "collection": collected,
            "current": current,
            "run": run,
        }
        (self.output / f"{label}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"{label}: HTTP {response.status_code}; {len(items)} evidências; "
            f"resultado={run['response']['outcome']}; simulado={run['simulated']}",
            flush=True,
        )
        print(f"Diagnóstico: {run['response']['summary']}", flush=True)
        print(f"Evidências e diagnóstico: {self.output / f'{label}.json'}", flush=True)
        return result

    def run(self) -> bool:
        self.output.mkdir(parents=True, exist_ok=False)
        phases: list[dict[str, Any]] = []
        control: list[dict[str, str]] = []
        restored = False
        error: str | None = None
        running = self.docker("ps", "--services", "--status", "running").stdout.splitlines()
        required = {"gateway", "orders-service", "users-service", "postgres", "etcd"}
        if not required <= set(running):
            raise RuntimeError("Execute docker compose up --build -d --wait antes da demonstração")
        collector_was_running = "collector" in running

        def event(action: str) -> None:
            control.append({"timestamp": datetime.now(UTC).isoformat(), "action": action})

        try:
            # Um único escritor JSONL/checkpoint por vez.
            if collector_was_running:
                self.docker("stop", "collector")
            self.wait_users()
            self.present(
                "CENA 1 — Atendimento normal. Confirmar a consulta do pedido antes do incidente."
            )
            phases.append(self.phase("normal", 200))
            self.present(
                "CENA 2 — Incidente simulado. Users será interrompido. "
                "Observe a operação do cliente e o health local do Gateway."
            )
            event("stop users-service")
            self.docker("stop", "users-service")
            phases.append(self.phase("indisponibilidade", 503))
            self.present(
                "CENA 3 — Conferir o diagnóstico e abrir uma evidência citada. "
                "Ao continuar, Users será restaurado e a consulta será verificada."
            )
            event("start users-service")
            self.docker("start", "users-service")
            self.wait_users()
            phases.append(self.phase("recuperacao", 200))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                self.docker("start", "users-service")
                self.wait_users()
                restored = True
                event("users-service restored")
            except Exception as exc:
                error = (error or "") + f" Recuperação falhou: {type(exc).__name__}"
                event("users-service restoration failed")
            if collector_was_running:
                try:
                    self.docker("start", "collector")
                except Exception as exc:
                    error = (error or "") + f" Reinício do coletor falhou: {type(exc).__name__}"
            (self.output / "controle-experimental.json").write_text(
                json.dumps(control, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        successful = (
            error is None
            and len(phases) == 3
            and restored
            and all(phase["run"]["response"]["outcome"] != "failure" for phase in phases)
        )
        real_llm_used = bool(phases) and all(not p["run"]["simulated"] for p in phases)
        outcomes_match = len(phases) == 3 and [p["run"]["response"]["outcome"] for p in phases] == [
            "no_incident",
            "incident",
            "no_incident",
        ]
        if outcomes_match:
            outcomes_match = any(
                hypothesis.get("service") == "users-service"
                for hypothesis in phases[1]["run"]["response"]["hypotheses"]
            )
        diagnostic_passed = successful and real_llm_used and outcomes_match
        summary = {
            "executed_at": datetime.now(UTC).isoformat(),
            "pipeline_passed": successful,
            "users_restored": restored,
            "error": error,
            "real_llm_used": real_llm_used,
            "diagnostic_demonstration_passed": diagnostic_passed,
            "expected_outcomes_observed": outcomes_match,
            "phases": [
                {
                    "phase": p["phase"],
                    "http_status": p["http_status"],
                    "request_id": p["request_id"],
                    "run_id": p["run"]["run_id"],
                    "outcome": p["run"]["response"]["outcome"],
                    "simulated": p["run"]["simulated"],
                    "operation": p["operation"],
                }
                for p in phases
            ],
            "scope": "Demonstração de viabilidade; não é avaliação formal de acurácia.",
        }
        (self.output / "resumo.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        lines = [
            "# Registro da demonstração",
            "",
            f"Data UTC: {summary['executed_at']}",
            "",
            f"Pipeline verificado: {successful}. Users recuperado: {restored}.",
            f"LLM real utilizada: {summary['real_llm_used']}.",
            f"Resultados esperados com LLM real observados: {diagnostic_passed}.",
            "",
            "| Etapa | HTTP | Resultado | Simulado | Execução |",
            "| --- | --- | --- | --- | --- |",
        ]
        for phase in phases:
            run = phase["run"]
            lines.append(
                f"| {phase['phase']} | {phase['http_status']} | "
                f"{run['response']['outcome']} | {run['simulated']} | {run['run_id']} |"
            )
        lines += [
            "",
            "## Operação de negócio observada",
            "",
            "Amostras sequenciais de consulta de pedido; não representam teste de carga.",
            "",
            "| Etapa | Consultas com falha | Taxa de falha | "
            "Média no cliente (ms) | Health Gateway |",
            "| --- | --- | --- | --- | --- |",
        ]
        for phase in phases:
            operation = phase["operation"]
            lines.append(
                f"| {phase['phase']} | "
                f"{operation['failed_queries']}/{operation['sample_count']} | "
                f"{operation['failure_rate_percent']}% | {operation['mean_elapsed_ms']} | "
                f"{operation['gateway_health_status']} |"
            )
        lines += [
            "",
            "## Diagnósticos e decisão humana",
        ]
        for phase in phases:
            response = phase["run"]["response"]
            lines += ["", f"### {phase['phase']}", "", response["summary"]]
            for hypothesis in response["hypotheses"]:
                lines += [
                    "",
                    f"- Hipótese: {hypothesis['description']}",
                    f"- Evidências: {', '.join(hypothesis['evidence_ids'])}",
                ]
            for limitation in response["limitations"]:
                lines.append(f"- Limitação: {limitation}")
        lines += [
            "",
            "Arquivos JSON contêm os contextos, evidências, respostas e tentativas.",
            "O arquivo controle-experimental.json não é ingerido pelo sistema.",
            "A recuperação é uma ação do controlador experimental; "
            "o diagnóstico não executa comandos.",
            "Não foram medidos ganhos de tempo de investigação ou impactos financeiros.",
        ]
        if error:
            lines += ["", f"Falha observada: {error}"]
        (self.output / "relatorio.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Relatório: {self.output / 'relatorio.md'}", flush=True)
        return diagnostic_passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Nome do projeto Compose")
    parser.add_argument("--port", default=os.environ.get("GATEWAY_PORT", "8000"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--interactive", action="store_true", help="Pausas guiadas para apresentação ao vivo"
    )
    parser.add_argument(
        "--samples", type=int, default=3, help="Consultas sequenciais adicionais por etapa (1 a 10)"
    )
    args = parser.parse_args()
    if not 1 <= args.samples <= 10:
        parser.error("--samples deve estar entre 1 e 10")
    output = args.output or ROOT / "docs" / "evidencias" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    )
    success = Demonstration(
        args.project, args.port, output, interactive=args.interactive, samples=args.samples
    ).run()
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
