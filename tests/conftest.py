from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "SERVICE_NAME",
        "USERS_SERVICE_URL",
        "ORDERS_SERVICE_URL",
        "HTTP_TIMEOUT_SECONDS",
        "LOG_LEVEL",
        "LOG_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    # Não carregar .env do desenvolvedor durante os testes.
    monkeypatch.chdir(tmp_path)
