import pytest
from app.config import Settings
from pydantic import ValidationError


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "orders-service")
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "0.5")
    monkeypatch.setenv("USERS_SERVICE_URL", "http://127.0.0.1:8001")
    settings = Settings()
    assert settings.service_name == "orders-service"
    assert settings.http_timeout_seconds == 0.5
    assert str(settings.users_service_url) == "http://127.0.0.1:8001/"


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_rejects_invalid_timeout(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", value)
    with pytest.raises(ValidationError):
        Settings()
