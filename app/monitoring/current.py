import json
from typing import Any
from urllib.parse import urlsplit

from etcd3gw.client import Etcd3Client

from app.config import MonitorSettings
from app.monitoring.models import Snapshot, Thresholds

CURRENT_KEY = "/observability/snapshot/current"
THRESHOLDS_KEY = "/observability/thresholds"
TRIGGER_KEY = "/observability/trigger/last"


def etcd_client(settings: MonitorSettings, timeout: float | None) -> Etcd3Client:
    url = urlsplit(str(settings.etcd_url))
    client = Etcd3Client(
        host=url.hostname or "etcd",
        port=url.port or 2379,
        protocol=url.scheme,
        timeout=timeout,
        api_path="/v3/",
    )
    client.session.trust_env = False
    return client


class CurrentState:
    def __init__(self, settings: MonitorSettings) -> None:
        self.client = etcd_client(settings, settings.timeout_seconds)
        self.ttl = settings.snapshot_ttl_seconds

    def publish(self, snapshot: Snapshot) -> None:
        lease = self.client.lease(self.ttl)
        self.client.put(CURRENT_KEY, snapshot.model_dump_json(), lease=lease)

    def read(self) -> Snapshot | None:
        values = self.client.get(CURRENT_KEY)
        return Snapshot.model_validate_json(values[0]) if values else None

    def read_thresholds(self) -> Thresholds:
        # Sem chave no etcd valem os padrões; alterar a chave muda o gatilho em execução.
        values = self.client.get(THRESHOLDS_KEY)
        return Thresholds.model_validate_json(values[0]) if values else Thresholds()

    def write_thresholds(self, thresholds: Thresholds) -> None:
        self.client.put(THRESHOLDS_KEY, thresholds.model_dump_json())

    def read_trigger(self) -> dict[str, Any] | None:
        values = self.client.get(TRIGGER_KEY)
        if not values:
            return None
        record: dict[str, Any] = json.loads(values[0])
        return record

    def write_trigger(self, record: dict[str, Any]) -> None:
        self.client.put(TRIGGER_KEY, json.dumps(record, ensure_ascii=False))

    def close(self) -> None:
        self.client.session.close()
