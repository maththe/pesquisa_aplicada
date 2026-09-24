from dataclasses import dataclass
from time import perf_counter

import httpx
from pydantic import BaseModel, ValidationError

from app.config import ServiceName, Settings
from app.telemetry import EventLogger, request_id_context


@dataclass
class ServiceRuntime:
    settings: Settings
    events: EventLogger
    client: httpx.AsyncClient | None = None

    def dependency(self, service: ServiceName, url: str) -> "ServiceClient":
        if self.client is None:
            raise RuntimeError("HTTP client has not started")
        return ServiceClient(self.client, self.events, service, url)

    def users(self) -> "ServiceClient":
        return self.dependency("users-service", str(self.settings.users_service_url))

    def orders(self) -> "ServiceClient":
        return self.dependency("orders-service", str(self.settings.orders_service_url))


class DependencyFailure(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ServiceClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        events: EventLogger,
        dependency: ServiceName,
        base_url: str,
    ) -> None:
        self.client = client
        self.events = events
        self.dependency = dependency
        self.base_url = base_url.rstrip("/")

    async def get[ResponseModel: BaseModel](
        self, path: str, response_model: type[ResponseModel]
    ) -> ResponseModel:
        request_id = request_id_context.get()
        headers = {"X-Request-ID": request_id} if request_id is not None else {}
        started = perf_counter()
        try:
            response = await self.client.get(f"{self.base_url}{path}", headers=headers)
        except httpx.TimeoutException as exc:
            self._log_failure("dependency_timeout", started, path, exc)
            raise DependencyFailure(504, f"Timeout ao consultar {self.dependency}") from exc
        except httpx.RequestError as exc:
            self._log_failure("dependency_unavailable", started, path, exc)
            raise DependencyFailure(503, f"Dependência indisponível: {self.dependency}") from exc

        if response.status_code >= 400:
            self.events.emit(
                "ERROR" if response.status_code >= 500 else "WARNING",
                "dependency_http_error",
                "Dependência retornou erro HTTP",
                dependency=self.dependency,
                duration_ms=(perf_counter() - started) * 1000,
                method="GET",
                path=path,
                status_code=response.status_code,
            )
            raise DependencyFailure(response.status_code, f"Erro ao consultar {self.dependency}")

        try:
            result = response_model.model_validate_json(response.content)
        except ValidationError as exc:
            self._log_failure("dependency_invalid_response", started, path, exc)
            raise DependencyFailure(502, f"Resposta inválida de {self.dependency}") from exc

        self.events.emit(
            "INFO",
            "dependency_completed",
            "Consulta à dependência concluída",
            dependency=self.dependency,
            duration_ms=(perf_counter() - started) * 1000,
            method="GET",
            path=path,
            status_code=response.status_code,
        )
        return result

    def _log_failure(self, event: str, started: float, path: str, exc: Exception) -> None:
        self.events.emit(
            "ERROR",
            event,
            f"Falha ao consultar {self.dependency}",
            dependency=self.dependency,
            duration_ms=(perf_counter() - started) * 1000,
            method="GET",
            path=path,
            error_type=type(exc).__name__,
        )
