"""Remote presentation contract: authentication, origins and background execution."""

import threading
import time
from collections.abc import Iterator
from unittest.mock import patch

import httpx
import pytest
from presentation import app


@pytest.fixture
def remote_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[httpx.Client]:
    monkeypatch.setenv("PRESENTATION_API_TOKEN", "a" * 32)
    monkeypatch.setenv("PRESENTATION_ALLOWED_ORIGINS", "https://demo.vercel.app")
    monkeypatch.setattr(app, "JOBS", app.JobStore())
    server = app.create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False) as client:
        yield client
    server.shutdown()
    server.server_close()
    thread.join()


HEADERS = {"Authorization": "Bearer " + "a" * 32, "Origin": "https://demo.vercel.app"}


def test_remote_access_requires_token_and_exact_origin(remote_api: httpx.Client) -> None:
    with patch.object(app.JOBS, "submit") as submit:
        assert remote_api.post("/api/failure").status_code == 401
        assert (
            remote_api.post(
                "/api/failure", headers={**HEADERS, "Origin": "https://other.vercel.app"}
            ).status_code
            == 403
        )
        assert remote_api.post("/api/arbitrary-command", headers=HEADERS).status_code == 404
        submit.assert_not_called()
    response = remote_api.get("/api/health", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == HEADERS["Origin"]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["api_version"] == 1


def test_cors_preflight(remote_api: httpx.Client) -> None:
    response = remote_api.options("/api/normal", headers={"Origin": HEADERS["Origin"]})
    assert response.status_code == 204
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]
    assert (
        remote_api.options("/api/normal", headers={"Origin": "https://evil.example"}).status_code
        == 403
    )


def test_background_job_returns_result_and_rejects_parallel_scenarios(
    remote_api: httpx.Client,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def scenario(action: str) -> dict[str, str]:
        started.set()
        assert release.wait(5)
        return {"scenario": action}

    with patch.object(app, "run_action", side_effect=scenario):
        try:
            response = remote_api.post("/api/normal", headers=HEADERS)
            assert response.status_code == 202
            assert started.wait(2)
            job_id = response.json()["id"]
            assert remote_api.post("/api/failure", headers=HEADERS).status_code == 409
            path = f"/api/jobs/{job_id}"
            assert remote_api.get(path).status_code == 401
            assert remote_api.get(path, headers=HEADERS).json()["state"] == "running"
        finally:
            release.set()
        for _ in range(100):
            job = remote_api.get(path, headers=HEADERS).json()
            if job["state"] == "completed":
                break
            time.sleep(0.01)
        assert job["result"] == {"scenario": "normal"}


def test_errors_do_not_expose_backend_secrets(remote_api: httpx.Client) -> None:
    with patch.object(app, "run_action", side_effect=RuntimeError("secret-from-driver")):
        job_id = remote_api.post("/api/normal", headers=HEADERS).json()["id"]
        for _ in range(100):
            response = remote_api.get(f"/api/jobs/{job_id}", headers=HEADERS)
            if response.json()["state"] == "failed":
                break
            time.sleep(0.01)
        assert response.json()["state"] == "failed"
        assert "secret-from-driver" not in response.text
    assert remote_api.get("/api/jobs/missing", headers=HEADERS).status_code == 404


def test_remote_bind_refuses_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRESENTATION_API_TOKEN", raising=False)
    with pytest.raises(ValueError, match="PRESENTATION_API_TOKEN"):
        app.create_server("0.0.0.0", 0)


def test_llm_failure_preserves_http_observation() -> None:
    observation = {"scenario": "normal", "checks": {"order": {"status": 200}}}
    with patch.object(app, "add_ai_diagnosis", side_effect=RuntimeError("private detail")):
        result = app.with_ai_diagnosis(observation, "2026-10-22T00:00:00Z")
    assert result["checks"]["order"]["status"] == 200
    assert "ai_error" in result
    assert "private detail" not in result["ai_error"]
