from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import socket
import ssl
import tempfile
import unittest

from api_support_operations.catalog import parse_catalog
from api_support_operations.monitoring import (
    HealthCheckEngine,
    MonitoringConfigurationError,
    TransportResponse,
    load_monitoring_configuration,
)
from api_support_operations.monitoring_pipeline import (
    build_fixture_artifacts,
    enforce_live_interval,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPOSITORY_ROOT / "config" / "monitoring_targets.json"
FIXTURES = REPOSITORY_ROOT / "data" / "mock_health_runs.json"
REGISTRY_SOURCE = REPOSITORY_ROOT / "data" / "public_apis_excerpt.md"
ARTIFACTS = REPOSITORY_ROOT / "artifacts"
MONITORING_ARTIFACTS = (
    "health_check_history.csv",
    "health_check_results.json",
    "latency_history.json",
    "monitoring_summary.json",
)


class StubClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, milliseconds: int) -> None:
        self.value += milliseconds / 1000


class StubTransport:
    def __init__(self, behaviors: dict[str, object], clock: StubClock) -> None:
        self.behaviors = behaviors
        self.clock = clock
        self.calls: list[dict[str, object]] = []

    def request(self, **request: object) -> TransportResponse:
        self.calls.append(request)
        behavior = self.behaviors[str(request["url"])]
        latency_ms, response_or_error = behavior
        self.clock.advance(latency_ms)
        if isinstance(response_or_error, Exception):
            raise response_or_error
        return response_or_error


class MonitoringConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        records = parse_catalog(REGISTRY_SOURCE.read_text(encoding="utf-8"))
        self.eligible_ids = {
            record.api_id for record in records if record.monitoring_eligible
        }

    def test_reviewed_allowlist_is_separate_from_catalog_eligibility(self) -> None:
        configuration = load_monitoring_configuration(
            CONFIG,
            monitoring_eligible_api_ids=self.eligible_ids,
        )
        self.assertFalse(configuration.policy.catalog_inclusion_authorizes_requests)
        self.assertEqual(configuration.policy.minimum_interval_minutes, 60)
        self.assertEqual(len(configuration.targets), 3)
        self.assertTrue(
            all(target.policy_review_status == "reviewed" for target in configuration.targets)
        )
        self.assertTrue(all(target.endpoint.startswith("https://") for target in configuration.targets))

    def test_catalog_authorization_flag_is_rejected(self) -> None:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
        payload["policy"]["catalog_inclusion_authorizes_requests"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                MonitoringConfigurationError,
                "Catalog inclusion must not authorize requests",
            ):
                load_monitoring_configuration(path)

    def test_unreviewed_target_is_rejected_even_when_catalog_eligible(self) -> None:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
        payload["targets"][0]["policy_review_status"] = "pending"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MonitoringConfigurationError, "Target is not reviewed"):
                load_monitoring_configuration(
                    path,
                    monitoring_eligible_api_ids=self.eligible_ids,
                )


class HealthCheckEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        records = parse_catalog(REGISTRY_SOURCE.read_text(encoding="utf-8"))
        eligible_ids = {record.api_id for record in records if record.monitoring_eligible}
        self.configuration = load_monitoring_configuration(
            CONFIG,
            monitoring_eligible_api_ids=eligible_ids,
        )

    def _behaviors(self, replacement: dict[str, object] | None = None) -> dict[str, object]:
        behaviors: dict[str, object] = {
            target.endpoint: (
                125,
                TransportResponse(200, {"Content-Type": "application/json; charset=utf-8"}),
            )
            for target in self.configuration.targets
        }
        behaviors.update(replacement or {})
        return behaviors

    def test_healthy_check_captures_status_latency_and_request_guardrails(self) -> None:
        clock = StubClock()
        transport = StubTransport(self._behaviors(), clock)
        results = HealthCheckEngine(
            self.configuration,
            transport,
            monotonic=clock,
        ).run(run_id="test-run", observed_at="2026-08-17T12:00:00Z")

        self.assertEqual(len(results), 3)
        self.assertTrue(all(result.status_code == 200 for result in results))
        self.assertTrue(all(result.latency_ms == 125 for result in results))
        self.assertTrue(all(result.outcome == "healthy" for result in results))
        self.assertTrue(
            all(
                call["headers"]["User-Agent"] == self.configuration.policy.user_agent
                for call in transport.calls
            )
        )
        self.assertEqual(
            [call["timeout_seconds"] for call in transport.calls],
            [target.timeout_seconds for target in self.configuration.targets],
        )

    def test_contract_and_http_failures_have_distinct_taxonomy(self) -> None:
        first, second, _ = self.configuration.targets
        clock = StubClock()
        transport = StubTransport(
            self._behaviors(
                {
                    first.endpoint: (80, TransportResponse(503, {"Content-Type": "application/json"})),
                    second.endpoint: (90, TransportResponse(200, {"Content-Type": "text/html"})),
                }
            ),
            clock,
        )
        results = HealthCheckEngine(self.configuration, transport, monotonic=clock).run(
            run_id="test-run",
            observed_at="2026-08-17T12:00:00Z",
        )

        by_id = {result.api_id: result for result in results}
        self.assertEqual(by_id[first.api_id].error_type, "http_status")
        self.assertEqual(by_id[first.api_id].outcome, "unhealthy")
        self.assertEqual(by_id[second.api_id].error_type, "response_contract")
        self.assertEqual(by_id[second.api_id].outcome, "degraded")

    def test_network_failure_taxonomy(self) -> None:
        target = self.configuration.targets[0]
        cases = (
            (TimeoutError(), "timeout"),
            (socket.gaierror(), "dns_error"),
            (ssl.SSLError(), "tls_error"),
            (ConnectionRefusedError(), "connection_error"),
            (RuntimeError(), "unexpected_error"),
        )
        for error, expected in cases:
            with self.subTest(expected=expected):
                clock = StubClock()
                transport = StubTransport(
                    self._behaviors({target.endpoint: (50, error)}),
                    clock,
                )
                results = HealthCheckEngine(
                    self.configuration,
                    transport,
                    monotonic=clock,
                ).run(run_id="test-run", observed_at="2026-08-17T12:00:00Z")
                self.assertEqual(results[0].error_type, expected)
                self.assertEqual(results[0].latency_ms, 50)
                self.assertEqual(len(results), 3, "one failure must not stop later targets")


class MonitoringPipelineTests(unittest.TestCase):
    def test_live_interval_uses_runtime_history_to_limit_request_volume(self) -> None:
        records = parse_catalog(REGISTRY_SOURCE.read_text(encoding="utf-8"))
        eligible_ids = {record.api_id for record in records if record.monitoring_eligible}
        configuration = load_monitoring_configuration(
            CONFIG,
            monitoring_eligible_api_ids=eligible_ids,
        )
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory)
            (output_directory / "live-20260817-120000.json").write_text(
                json.dumps(
                    [
                        {
                            "api_id": "weather-open-meteo",
                            "observed_at": "2026-08-17T12:00:00Z",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "minimum interval"):
                enforce_live_interval(
                    configuration,
                    output_directory,
                    datetime(2026, 8, 17, 12, 30, tzinfo=timezone.utc),
                )
            enforce_live_interval(
                configuration,
                output_directory,
                datetime(2026, 8, 17, 13, 0, tzinfo=timezone.utc),
            )

    def test_fixture_outputs_are_byte_for_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_directory = Path(first)
            second_directory = Path(second)
            first_summary = build_fixture_artifacts(
                CONFIG, FIXTURES, REGISTRY_SOURCE, first_directory
            )
            second_summary = build_fixture_artifacts(
                CONFIG, FIXTURES, REGISTRY_SOURCE, second_directory
            )
            self.assertEqual(first_summary, second_summary)
            self.assertEqual(first_summary["check_count"], 21)
            for filename in MONITORING_ARTIFACTS:
                self.assertEqual(
                    (first_directory / filename).read_bytes(),
                    (second_directory / filename).read_bytes(),
                )

    def test_tracked_monitoring_artifacts_match_fixture_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory)
            build_fixture_artifacts(CONFIG, FIXTURES, REGISTRY_SOURCE, generated)
            for filename in MONITORING_ARTIFACTS:
                self.assertEqual(
                    (ARTIFACTS / filename).read_bytes(),
                    (generated / filename).read_bytes(),
                    filename,
                )


if __name__ == "__main__":
    unittest.main()
