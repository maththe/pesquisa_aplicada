from dataclasses import dataclass

import httpx

from app.config import Settings
from app.services.http import ServiceClient
from app.telemetry import EventLogger


@dataclass
class ServiceRuntime:
    settings: Settings
    events: EventLogger
    client: httpx.AsyncClient | None = None

    def users(self) -> ServiceClient:
        if self.client is None:
            raise RuntimeError("HTTP client has not started")
        return ServiceClient(
            self.client, self.events, "users-service", str(self.settings.users_service_url)
        )

    def orders(self) -> ServiceClient:
        if self.client is None:
            raise RuntimeError("HTTP client has not started")
        return ServiceClient(
            self.client, self.events, "orders-service", str(self.settings.orders_service_url)
        )
