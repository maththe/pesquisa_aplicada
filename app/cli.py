import argparse
import asyncio
import json
import sys
from datetime import timedelta
from typing import Any

from pydantic import BaseModel

from app.observability.collector import collect_once
from app.observability.config import MonitorSettings
from app.observability.context import build_context
from app.observability.current import CurrentState
from app.observability.database import migrate
from app.observability.diagnostics import diagnose
from app.observability.models import DiagnosticRequest, utcnow
from app.observability.providers import make_provider
from app.observability.storage import History


def emit(value: Any) -> None:
    if isinstance(value, BaseModel):
        print(value.model_dump_json(indent=2), flush=True)
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Diagnóstico distribuído com evidências")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="Aplica migrações do histórico")
    collect = commands.add_parser("collect", help="Coleta métricas, logs e estado atual")
    collect.add_argument("--once", action="store_true")
    commands.add_parser("current", help="Consulta o snapshot válido no etcd")
    for name in ("context", "diagnose"):
        command = commands.add_parser(name)
        command.add_argument("--start", help="Início ISO 8601 com timezone; padrão: últimos 5 min")
        command.add_argument("--end", help="Fim ISO 8601 com timezone; padrão: agora")
        command.add_argument("--service", choices=["gateway", "orders-service", "users-service"])
        command.add_argument("--request-id", help="X-Request-ID da requisição de negócio")
    commands.add_parser("history", help="Últimas 20 execuções")
    commands.add_parser("evidence", help="Evidência original e data de ingestão").add_argument("id")
    commands.add_parser("run", help="Execução completa pelo ID").add_argument("id")
    return root


async def execute(args: argparse.Namespace, settings: MonitorSettings) -> int:
    history = History(settings.database_url)
    try:
        if args.command == "init-db":
            migrate(history)
            emit({"schema": "001", "status": "ready"})
        elif args.command in ("collect", "current"):
            current = CurrentState(settings)
            try:
                if args.command == "current":
                    snapshot = await asyncio.to_thread(current.read)
                    emit(snapshot if snapshot else {"status": "missing_or_expired"})
                    return 0 if snapshot else 1
                while True:
                    try:
                        result = await collect_once(settings, history, current)
                    except Exception as exc:
                        emit({"status": "collection_failed", "error": type(exc).__name__})
                        if args.once:
                            return 1
                    else:
                        emit(result)
                        if args.once:
                            return 0 if result["current_published"] else 1
                    await asyncio.sleep(settings.interval_seconds)
            finally:
                current.close()
        elif args.command in ("context", "diagnose"):
            end = args.end or utcnow().isoformat()
            from datetime import datetime

            start = args.start or (datetime.fromisoformat(end) - timedelta(minutes=5)).isoformat()
            request = DiagnosticRequest.model_validate(
                {
                    "start": start,
                    "end": end,
                    "service": args.service,
                    "correlation_id": args.request_id,
                }
            )
            context = build_context(history, request, settings)
            if args.command == "context":
                emit(context)
            else:
                run = await diagnose(context, make_provider(settings), history)
                emit(run)
                return 1 if run.response.outcome == "failure" else 0
        elif args.command == "history":
            emit(
                [
                    {
                        "run_id": run.run_id,
                        "timestamp": run.timestamp.isoformat(),
                        "outcome": run.response.outcome,
                        "simulated": run.simulated,
                        "summary": run.response.summary,
                    }
                    for run in history.recent_runs()
                ]
            )
        elif args.command == "evidence":
            item = history.get_evidence(args.id)
            emit(item)
            return 0 if item else 1
        elif args.command == "run":
            found_run = history.get_run(args.id)
            emit(found_run)
            return 0 if found_run else 1
        return 0
    finally:
        history.close()


def main() -> None:
    args = parser().parse_args()
    try:
        code = asyncio.run(execute(args, MonitorSettings()))
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:
        # Evita expor DSNs/chaves em mensagens de driver.
        print(f"Falha: {type(exc).__name__}. Verifique configuração e serviços.", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
