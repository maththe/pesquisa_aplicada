import asyncio
import re
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import LogLevel
from app.telemetry import EventLogger, request_id_context

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp, events: EventLogger) -> None:
        self.app = app
        self.events = events

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else str(uuid4())
        token = request_id_context.set(request_id)
        started = perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            # Última fronteira HTTP: manter correlação também em erros inesperados.
            self.events.emit(
                "ERROR",
                "unhandled_exception",
                "Erro inesperado ao processar requisição",
                method=scope["method"],
                path=scope["path"],
                error_type=type(exc).__name__,
            )
            if response_started:
                raise
            response = JSONResponse({"detail": "Internal server error"}, status_code=500)
            await response(scope, receive, send_with_request_id)
        finally:
            level: LogLevel = (
                "ERROR" if status_code >= 500 else ("WARNING" if status_code >= 400 else "INFO")
            )
            try:
                self.events.emit(
                    level,
                    "request_completed",
                    "Requisição concluída",
                    duration_ms=(perf_counter() - started) * 1000,
                    method=scope["method"],
                    path=scope["path"],
                    status_code=status_code,
                )
            finally:
                request_id_context.reset(token)


class OverloadGuardMiddleware:
    """Recusa excesso de concorrência em um experimento explicitamente habilitado."""

    def __init__(
        self,
        app: ASGIApp,
        events: EventLogger,
        concurrency_limit: int,
        delay_ms: int,
    ) -> None:
        self.app = app
        self.events = events
        self.concurrency_limit = concurrency_limit
        self.delay_seconds = delay_ms / 1000
        self.in_flight = 0
        self.lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or self.concurrency_limit == 0
            or scope["path"] in ("/health", "/metrics")
        ):
            await self.app(scope, receive, send)
            return

        async with self.lock:
            self.in_flight += 1
            current = self.in_flight
        try:
            if current > self.concurrency_limit:
                self.events.emit(
                    "ERROR",
                    "overload_rejected",
                    (
                        f"Sobrecarga: {current} requisições simultâneas excederam "
                        f"o limite {self.concurrency_limit}; requisição recusada"
                    ),
                    method=scope["method"],
                    path=scope["path"],
                    status_code=503,
                    error_type="ConcurrencyLimitExceeded",
                )
                response = JSONResponse(
                    {"detail": "Serviço saturado por excesso de requisições"},
                    status_code=503,
                )
                await response(scope, receive, send)
                return
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            await self.app(scope, receive, send)
        finally:
            async with self.lock:
                self.in_flight -= 1
