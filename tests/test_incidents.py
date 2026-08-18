from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from api_support_operations.incident_pipeline import build_incident_artifacts
from api_support_operations.incidents import (
    IncidentConfigurationError,
    build_incidents,
    load_incident_configuration,
)
from api_support_operations.monitoring import HealthCheckResult
from api_support_operations.monitoring_pipeline import build_fixture_artifacts


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INCIDENT_CONFIG = REPOSITORY_ROOT / "config" / "incident_policy.json"
MONITORING_CONFIG = REPOSITORY_ROOT / "config" / "monitoring_targets.json"
FIXTURES = REPOSITORY_ROOT / "data" / "mock_health_runs.json"
REGISTRY_SOURCE = REPOSITORY_ROOT / "data" / "public_apis_excerpt.md"
ARTIFACTS = REPOSITORY_ROOT / "artifacts"
INCIDENT_ARTIFACTS = (
    "incident_summary.json",
    "incident_timeline.csv",
    "incidents.json",
)


def _fixture_incidents() -> list[object]:
    with tempfile.TemporaryDirectory() as directory:
        generated = Path(directory)
        build_fixture_artifacts(
            MONITORING_CONFIG,
            FIXTURES,
            REGISTRY_SOURCE,
            generated,
        )
        payload = json.loads((generated / "health_check_results.json").read_text(encoding="utf-8"))
    results = [HealthCheckResult(**item) for item in payload]
    configuration = load_incident_configuration(
        INCIDENT_CONFIG,
        monitored_api_ids={result.api_id for result in results},
    )
    return build_incidents(results, configuration)


class IncidentConfigurationTests(unittest.TestCase):
    def test_policy_covers_every_monitored_api_with_auditable_assumptions(self) -> None:
        configuration = load_incident_configuration(
            INCIDENT_CONFIG,
            monitored_api_ids={
                "art-design-art-institute-of-chicago",
                "vehicle-nhtsa",
                "weather-open-meteo",
            },
        )

        self.assertEqual(len(configuration.services), 3)
        self.assertTrue(all(service.owner for service in configuration.services))
        self.assertTrue(
            all(
                "Synthetic portfolio assumption" in service.criticality_basis
                for service in configuration.services
            )
        )
        self.assertLess(
            configuration.policy.availability_sev2_consecutive_failures,
            configuration.policy.availability_sev1_consecutive_failures,
        )

    def test_policy_rejects_criticality_presented_as_observed_impact(self) -> None:
        payload = json.loads(INCIDENT_CONFIG.read_text(encoding="utf-8"))
        payload["services"][0]["criticality_basis"] = "Customers depend on this provider."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                IncidentConfigurationError,
                "explicitly identified as synthetic",
            ):
                load_incident_configuration(path)


class IncidentRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.incidents = _fixture_incidents()

    def test_fixture_explicitly_covers_required_scenarios(self) -> None:
        payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
        scenarios = {
            response["scenario"]
            for run in payload["runs"]
            for response in run["responses"].values()
        }
        self.assertTrue(
            {
                "healthy_recovery",
                "intermittent_degradation",
                "sustained_outage",
                "rate_limiting",
                "authentication_failure",
                "schema_drift",
            }.issubset(scenarios)
        )

    def test_incident_identity_is_stable_and_evidence_is_auditable(self) -> None:
        repeated = _fixture_incidents()
        self.assertEqual(
            [incident.incident_id for incident in self.incidents],
            [incident.incident_id for incident in repeated],
        )
        self.assertTrue(all(incident.incident_id.startswith("inc-") for incident in self.incidents))
        self.assertTrue(
            all(
                evidence.run_id and evidence.observed_at and evidence.detail
                for incident in self.incidents
                for evidence in incident.evidence
            )
        )

    def test_healthy_observation_resolves_incident_and_closes_timestamps(self) -> None:
        self.assertTrue(all(incident.lifecycle_state == "resolved" for incident in self.incidents))
        self.assertTrue(
            all(incident.resolved_at == incident.last_observed_at for incident in self.incidents)
        )
        self.assertTrue(
            all(incident.evidence[-1].signal == "healthy_recovery" for incident in self.incidents)
        )

    def test_intermittent_latency_creates_distinct_incidents_after_recovery(self) -> None:
        latency_incidents = [
            incident
            for incident in self.incidents
            if incident.failure_type == "latency_degradation"
        ]
        self.assertEqual(len(latency_incidents), 2)
        self.assertEqual(len({incident.incident_id for incident in latency_incidents}), 2)
        self.assertEqual(
            [incident.severity for incident in latency_incidents],
            ["SEV-3", "SEV-2"],
        )
        self.assertIn("LATENCY_SEVERE_SEV2", latency_incidents[1].severity_rule_ids)

    def test_sustained_outage_escalates_by_consecutive_availability_failures(self) -> None:
        outage = next(
            incident for incident in self.incidents if incident.failure_type == "availability"
        )
        self.assertEqual(outage.consecutive_failure_count, 3)
        self.assertEqual(outage.severity, "SEV-1")
        self.assertIn("AVAILABILITY_SINGLE_SEV3", outage.severity_rule_ids)
        self.assertIn("AVAILABILITY_REPEATED_SEV2", outage.severity_rule_ids)
        self.assertIn("AVAILABILITY_SUSTAINED_SEV1", outage.severity_rule_ids)

    def test_http_signals_distinguish_rate_limit_and_authentication(self) -> None:
        by_type = {incident.failure_type: incident for incident in self.incidents}
        self.assertEqual(by_type["rate_limiting"].evidence[0].status_code, 429)
        self.assertEqual(
            [evidence.status_code for evidence in by_type["authentication_failure"].evidence[:-1]],
            [401, 403],
        )
        self.assertEqual(by_type["rate_limiting"].severity, "SEV-1")
        self.assertEqual(by_type["authentication_failure"].severity, "SEV-1")
        self.assertIn("HIGH_CRITICALITY_ESCALATION", by_type["rate_limiting"].severity_rule_ids)

    def test_response_contract_failure_becomes_schema_drift(self) -> None:
        schema_drift = next(
            incident for incident in self.incidents if incident.failure_type == "schema_drift"
        )
        self.assertEqual(schema_drift.severity, "SEV-3")
        self.assertEqual(schema_drift.evidence[0].error_type, "response_contract")
        self.assertIn("SCHEMA_DRIFT_SEV3", schema_drift.severity_rule_ids)

    def test_unknown_api_result_is_rejected_instead_of_silently_assigned(self) -> None:
        configuration = load_incident_configuration(INCIDENT_CONFIG)
        result = HealthCheckResult(
            run_id="unknown",
            observed_at="2026-08-17T12:00:00Z",
            api_id="unknown-api",
            endpoint="https://example.invalid/",
            status_code=503,
            latency_ms=10,
            outcome="unhealthy",
            error_type="http_status",
            error_detail="synthetic",
        )
        with self.assertRaisesRegex(ValueError, "no incident policy"):
            build_incidents([result], configuration)

    def test_unrecovered_failure_remains_open(self) -> None:
        configuration = load_incident_configuration(INCIDENT_CONFIG)
        result = HealthCheckResult(
            run_id="open-run",
            observed_at="2026-08-17T19:00:00Z",
            api_id="weather-open-meteo",
            endpoint="https://example.invalid/weather",
            status_code=503,
            latency_ms=100,
            outcome="unhealthy",
            error_type="http_status",
            error_detail="synthetic",
        )

        incident = build_incidents([result], configuration)[0]

        self.assertEqual(incident.lifecycle_state, "open")
        self.assertIsNone(incident.resolved_at)
        self.assertEqual(incident.first_observed_at, incident.last_observed_at)

    def test_changed_signal_is_superseded_without_inventing_recovery(self) -> None:
        configuration = load_incident_configuration(INCIDENT_CONFIG)
        shared = {
            "api_id": "vehicle-nhtsa",
            "endpoint": "https://example.invalid/vehicle",
            "latency_ms": 200,
            "outcome": "unhealthy",
            "error_type": "http_status",
            "error_detail": "synthetic",
        }
        results = [
            HealthCheckResult(
                run_id="rate-limit",
                observed_at="2026-08-17T19:00:00Z",
                status_code=429,
                **shared,
            ),
            HealthCheckResult(
                run_id="authentication",
                observed_at="2026-08-17T20:00:00Z",
                status_code=401,
                **shared,
            ),
        ]

        incidents = build_incidents(reversed(results), configuration)

        self.assertEqual(
            [incident.lifecycle_state for incident in incidents],
            ["superseded", "open"],
        )
        self.assertIsNone(incidents[0].resolved_at)
        self.assertNotIn(
            "healthy_recovery",
            [evidence.signal for evidence in incidents[0].evidence],
        )


class IncidentPipelineTests(unittest.TestCase):
    def test_incident_outputs_are_byte_for_byte_deterministic(self) -> None:
        with (
            tempfile.TemporaryDirectory() as health,
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            health_directory = Path(health)
            build_fixture_artifacts(
                MONITORING_CONFIG,
                FIXTURES,
                REGISTRY_SOURCE,
                health_directory,
            )
            first_directory = Path(first)
            second_directory = Path(second)
            first_summary = build_incident_artifacts(
                INCIDENT_CONFIG,
                health_directory / "health_check_results.json",
                first_directory,
            )
            second_summary = build_incident_artifacts(
                INCIDENT_CONFIG,
                health_directory / "health_check_results.json",
                second_directory,
            )
            self.assertEqual(first_summary, second_summary)
            self.assertEqual(first_summary["incident_count"], 6)
            self.assertEqual(first_summary["open_incident_count"], 0)
            for filename in INCIDENT_ARTIFACTS:
                self.assertEqual(
                    (first_directory / filename).read_bytes(),
                    (second_directory / filename).read_bytes(),
                )

    def test_tracked_incident_artifacts_match_full_fixture_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory)
            build_fixture_artifacts(
                MONITORING_CONFIG,
                FIXTURES,
                REGISTRY_SOURCE,
                generated,
            )
            build_incident_artifacts(
                INCIDENT_CONFIG,
                generated / "health_check_results.json",
                generated,
            )
            for filename in INCIDENT_ARTIFACTS:
                self.assertEqual(
                    (ARTIFACTS / filename).read_bytes(),
                    (generated / filename).read_bytes(),
                    filename,
                )


if __name__ == "__main__":
    unittest.main()
