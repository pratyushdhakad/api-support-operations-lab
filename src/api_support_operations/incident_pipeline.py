"""Build deterministic Day 3 incident artifacts from Day 2 health-check outputs."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from .incidents import Incident, build_incidents, load_incident_configuration
from .monitoring import HealthCheckResult


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPOSITORY_ROOT / "config" / "incident_policy.json"
DEFAULT_RESULTS = REPOSITORY_ROOT / "artifacts" / "health_check_results.json"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts"
CSV_FIELDS = (
    "incident_id",
    "lifecycle_state",
    "first_observed_at",
    "last_observed_at",
    "resolved_at",
    "failure_type",
    "api_id",
    "affected_api",
    "severity",
    "business_criticality",
    "owner",
    "consecutive_failure_count",
    "evidence_count",
    "recommended_action",
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_results(path: Path) -> list[HealthCheckResult]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Health-check result artifact must be a list")
    return [HealthCheckResult(**item) for item in payload]


def _write_csv(path: Path, incidents: list[Incident]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for incident in incidents:
            payload = incident.to_dict()
            payload["evidence_count"] = len(incident.evidence)
            writer.writerow(
                {
                    field: "" if payload.get(field) is None else payload.get(field)
                    for field in CSV_FIELDS
                }
            )


def _summary(incidents: list[Incident]) -> dict[str, object]:
    return {
        "failure_type_counts": dict(
            sorted(Counter(incident.failure_type for incident in incidents).items())
        ),
        "incident_count": len(incidents),
        "lifecycle_counts": dict(
            sorted(Counter(incident.lifecycle_state for incident in incidents).items())
        ),
        "open_incident_count": sum(
            incident.lifecycle_state == "open" for incident in incidents
        ),
        "severity_counts": dict(
            sorted(Counter(incident.severity for incident in incidents).items())
        ),
    }


def build_incident_artifacts(
    config_path: Path,
    health_results_path: Path,
    output_directory: Path,
) -> dict[str, object]:
    results = _load_results(health_results_path)
    monitored_api_ids = {result.api_id for result in results}
    configuration = load_incident_configuration(
        config_path,
        monitored_api_ids=monitored_api_ids,
    )
    incidents = build_incidents(results, configuration)
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_json(output_directory / "incidents.json", [incident.to_dict() for incident in incidents])
    _write_csv(output_directory / "incident_timeline.csv", incidents)
    summary = _summary(incidents)
    _write_json(output_directory / "incident_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--health-results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    arguments = parser.parse_args()
    summary = build_incident_artifacts(
        arguments.config,
        arguments.health_results,
        arguments.output_directory,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
