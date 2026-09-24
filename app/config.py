from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ServiceName = Literal["gateway", "users-service", "orders-service"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: ServiceName = "gateway"
    users_service_url: AnyHttpUrl = AnyHttpUrl("http://users-service:8000")
    orders_service_url: AnyHttpUrl = AnyHttpUrl("http://orders-service:8000")
    http_timeout_seconds: float = Field(default=2.0, gt=0)
    log_level: LogLevel = "INFO"
    log_dir: Path | None = None
