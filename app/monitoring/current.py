from urllib.parse import urlsplit

from etcd3gw.client import Etcd3Client

from app.config import MonitorSettings
from app.monitoring.models import Snapshot

CURRENT_KEY = "/observability/snapshot/current"


class CurrentState:
    def __init__(self, settings: MonitorSettings) -> None:
        url = urlsplit(str(settings.etcd_url))
        self.client = Etcd3Client(
            host=url.hostname or "etcd",
            port=url.port or 2379,
            protocol=url.scheme,
            timeout=settings.timeout_seconds,
            api_path="/v3/",
        )
        self.client.session.trust_env = False
        self.ttl = settings.snapshot_ttl_seconds

    def publish(self, snapshot: Snapshot) -> None:
        lease = self.client.lease(self.ttl)
        self.client.put(CURRENT_KEY, snapshot.model_dump_json(), lease=lease)

    def read(self) -> Snapshot | None:
        values = self.client.get(CURRENT_KEY)
        return Snapshot.model_validate_json(values[0]) if values else None

    def close(self) -> None:
        self.client.session.close()
