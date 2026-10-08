"""Verifica medições do cenário e recuperação sem Docker ou credenciais."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from experiments.demonstrate import Demonstration


class DemonstrationTests(unittest.TestCase):
    def test_operation_keeps_health_separate_from_failed_queries(self) -> None:
        correlations: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200)
            correlations.append(request.headers["X-Request-ID"])
            return httpx.Response(504)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            demo = Demonstration(None, "8000", output, samples=3)
            client = httpx.Client(transport=httpx.MockTransport(respond))
            with (
                patch("experiments.demonstrate.httpx.Client", return_value=client),
                patch(
                    "experiments.demonstrate.perf_counter",
                    side_effect=[0, 0.1, 1, 1.2, 2, 2.3],
                ),
            ):
                observation = demo.observe_operation("indisponibilidade")
            self.assertEqual(observation["gateway_health_status"], 200)
            self.assertEqual(observation["failed_queries"], 3)
            self.assertEqual(observation["failure_rate_percent"], 100)
            self.assertEqual(observation["mean_elapsed_ms"], 200)
            self.assertEqual(len(set(correlations)), 3)
            recorded = json.loads(
                (output / "indisponibilidade-operacao.json").read_text(encoding="utf-8")
            )
            self.assertEqual(recorded, observation)

    def test_successful_queries_have_zero_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            demo = Demonstration(None, "8000", Path(directory), samples=1)
            client = httpx.Client(
                transport=httpx.MockTransport(lambda request: httpx.Response(200))
            )
            with patch("experiments.demonstrate.httpx.Client", return_value=client):
                observation = demo.observe_operation("normal")
            self.assertEqual(observation["failed_queries"], 0)
            self.assertEqual(observation["failure_rate_percent"], 0)

    def test_invalid_sample_counts_are_rejected(self) -> None:
        for count in (0, -1, 11):
            with self.subTest(count=count), self.assertRaises(ValueError):
                Demonstration(None, "8000", Path("unused"), samples=count)

    def test_failure_restores_users_and_collector(self) -> None:
        running = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="gateway\norders-service\nusers-service\npostgres\netcd\ncollector\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "execution"
            demo = Demonstration(None, "8000", output)
            with (
                patch.object(demo, "docker", return_value=running) as docker,
                patch.object(demo, "wait_users"),
                patch.object(demo, "phase", side_effect=RuntimeError("Falha de medição")),
            ):
                self.assertFalse(demo.run())
            docker.assert_any_call("start", "users-service")
            docker.assert_any_call("start", "collector")
            summary = json.loads((output / "resumo.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["users_restored"])
            self.assertFalse(summary["diagnostic_demonstration_passed"])
            self.assertIn("Falha de medição", summary["error"])

    def test_interrupt_during_presentation_restores_services(self) -> None:
        running = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="gateway\norders-service\nusers-service\npostgres\netcd\ncollector\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            demo = Demonstration(None, "8000", Path(directory) / "execution", interactive=True)
            with (
                patch.object(demo, "docker", return_value=running) as docker,
                patch.object(demo, "wait_users"),
                patch("builtins.input", side_effect=KeyboardInterrupt),
                self.assertRaises(KeyboardInterrupt),
            ):
                demo.run()
            docker.assert_any_call("start", "users-service")
            docker.assert_any_call("start", "collector")

    def test_report_accepts_historical_diagnostic_schema(self) -> None:
        evidence = (
            Path(__file__).resolve().parents[1] / "docs" / "evidencias" / "20260924T221853Z-40eb62"
        )
        phases = []
        for label in ("normal", "indisponibilidade", "recuperacao"):
            phase = json.loads((evidence / f"{label}.json").read_text(encoding="utf-8"))
            # Medições sintéticas somente para testar o relatório; não são publicadas.
            phase["operation"] = {
                "sample_count": 1,
                "failed_queries": int(label == "indisponibilidade"),
                "failure_rate_percent": 100 if label == "indisponibilidade" else 0,
                "mean_elapsed_ms": 123,
                "gateway_health_status": 200,
            }
            phases.append(phase)
        running = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="gateway\norders-service\nusers-service\npostgres\netcd\ncollector\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "execution"
            demo = Demonstration(None, "8000", output)
            with (
                patch.object(demo, "docker", return_value=running),
                patch.object(demo, "wait_users"),
                patch.object(demo, "phase", side_effect=phases),
            ):
                self.assertTrue(demo.run())
            report = (output / "relatorio.md").read_text(encoding="utf-8")
            self.assertIn("| indisponibilidade | 1/1 | 100% | 123 | 200 |", report)
            hypothesis = phases[1]["run"]["response"]["hypotheses"][0]
            self.assertIn(hypothesis["description"], report)
            self.assertIn(hypothesis["evidence_ids"][0], report)


if __name__ == "__main__":
    unittest.main()
