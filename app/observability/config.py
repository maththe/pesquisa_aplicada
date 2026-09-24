from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import ServiceName


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
    llm_provider: Literal["fake", "langchain", "http"] = "fake"
    llm_url: AnyHttpUrl | None = None
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = Field(default=45, gt=0, le=180)

    @field_validator("llm_url", mode="before")
    @classmethod
    def empty_url(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_provider(self) -> "MonitorSettings":
        if self.llm_provider != "fake" and (self.llm_url is None or not self.llm_model.strip()):
            raise ValueError(
                "OBS_LLM_URL e OBS_LLM_MODEL são obrigatórios para o provedor LangChain"
            )
        if self.snapshot_ttl_seconds <= self.interval_seconds:
            raise ValueError("TTL do snapshot deve ser maior que o intervalo de coleta")
        return self

    def targets(self) -> dict[ServiceName, str]:
        return {
            "gateway": str(self.gateway_url).rstrip("/"),
            "orders-service": str(self.orders_url).rstrip("/"),
            "users-service": str(self.users_url).rstrip("/"),
        }
