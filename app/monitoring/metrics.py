import psutil

from app.config import ServiceName
from app.monitoring.models import Metrics


def sample_metrics(service: ServiceName) -> Metrics:
    result = Metrics(service=service)
    try:
        process = psutil.Process()
        result.process_rss_bytes = process.memory_info().rss
        result.process_threads = process.num_threads()
        result.system_cpu_percent = psutil.cpu_percent(interval=0.05)
        result.system_memory_percent = psutil.virtual_memory().percent
    except (psutil.Error, OSError):
        # Campos indisponíveis permanecem null.
        pass
    return result
