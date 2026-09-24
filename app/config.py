from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
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


class MonitorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OBS_", env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://observability:observability@postgres:5432/observability"
    )
    etcd_url: AnyHttpUrl = AnyHttpUrl("http://etcd:2379")
    gateway_url: AnyHttpUrl = AnyHttpUrl("http://gateway:8000")
    users_url: AnyHttpUrl = AnyHttpUrl("http://users-service:8000")
    orders_url: AnyHttpUrl = AnyHttpUrl("http://orders-service:8000")
    log_dir: Path = Path("/var/log/observability")
    interval_seconds: float = Field(default=5, gt=0)
    timeout_seconds: float = Field(default=2, gt=0)
    snapshot_ttl_seconds: int = Field(default=30, ge=5)
    context_max_items: int = Field(default=80, ge=1, le=500)
    context_max_chars: int = Field(default=50000, ge=3000, le=500000)
    llm_url: AnyHttpUrl | None = None
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = Field(default=45, gt=0, le=180)

    @field_validator("llm_url", mode="before")
    @classmethod
    def empty_url(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_collection(self) -> "MonitorSettings":
        if self.snapshot_ttl_seconds <= self.interval_seconds:
            raise ValueError("TTL do snapshot deve ser maior que o intervalo de coleta")
        return self

    def require_llm(self) -> None:
        if (
            self.llm_url is None
            or not self.llm_model.strip()
            or not self.llm_api_key.get_secret_value().strip()
        ):
            raise ValueError(
                "Configure OBS_LLM_URL, OBS_LLM_MODEL e OBS_LLM_API_KEY para diagnosticar."
            )

    def targets(self) -> dict[ServiceName, str]:
        return {
            "gateway": str(self.gateway_url).rstrip("/"),
            "orders-service": str(self.orders_url).rstrip("/"),
            "users-service": str(self.users_url).rstrip("/"),
        }
