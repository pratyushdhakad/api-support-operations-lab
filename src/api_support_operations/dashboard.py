"""Build the deterministic data contract consumed by the executive dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACTS = REPOSITORY_ROOT / "artifacts"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "site" / "data" / "dashboard.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _percentage(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 1) if denominator else 0.0


def build_dashboard_payload(
    artifacts_directory: Path = DEFAULT_ARTIFACTS,
) -> dict[str, object]:
    registry = _read_json(artifacts_directory / "api_registry.json")
    registry_summary = _read_json(artifacts_directory / "registry_summary.json")
    monitoring = _read_json(artifacts_directory / "monitoring_summary.json")
    latency_history = _read_json(artifacts_directory / "latency_history.json")
    incidents = _read_json(artifacts_directory / "incidents.json")
    incident_summary = _read_json(artifacts_directory / "incident_summary.json")
    classifications = _read_json(
        artifacts_directory / "incident_classifications.json"
    )
    evaluation = _read_json(artifacts_directory / "classification_evaluation.json")
    costs = _read_json(artifacts_directory / "classification_cost_summary.json")

    names_by_id = {item["api_id"]: item["name"] for item in registry}
    classifications_by_incident = {
        item["incident_id"]: item for item in classifications
    }
    observed_at = max(
        sample["observed_at"]
        for service in latency_history
        for sample in service["samples"]
    )

    outcome_counts = monitoring["outcome_counts"]
    severity_counts = incident_summary["severity_counts"]
    operating = evaluation["operating_point"]
    review_counts = evaluation["review_state_counts"]

    incident_rows = []
    for incident in incidents:
        classification = classifications_by_incident[incident["incident_id"]]
        incident_rows.append(
            {
                "confidence": classification["confidence"],
                "failure_category": classification["failure_category"],
                "first_observed_at": incident["first_observed_at"],
                "incident_id": incident["incident_id"],
                "lifecycle_state": incident["lifecycle_state"],
                "owner": classification["recommended_owner"],
                "priority": classification["priority"],
                "review_state": classification["review_state"],
                "service": incident["affected_api"],
                "summary": classification["summary"],
            }
        )
    severity_order = {"SEV-1": 1, "SEV-2": 2, "SEV-3": 3, "UNASSESSED": 4}
    incident_rows.sort(
        key=lambda item: (
            severity_order.get(str(item["priority"]), 99),
            str(item["first_observed_at"]),
            str(item["incident_id"]),
        )
    )

    services = []
    for service in latency_history:
        samples = service["samples"]
        latest = samples[-1]
        services.append(
            {
                "api_id": service["api_id"],
                "average_latency_ms": service["average_latency_ms"],
                "latest_latency_ms": latest["latency_ms"],
                "latest_outcome": latest["outcome"],
                "name": names_by_id.get(service["api_id"], service["api_id"]),
                "samples": [
                    {
                        "latency_ms": sample["latency_ms"],
                        "observed_at": sample["observed_at"],
                        "outcome": sample["outcome"],
                    }
                    for sample in samples
                ],
            }
        )

    return {
        "ai_evaluation": {
            "accuracy_on_answered_percent": round(
                operating["accuracy_on_answered"] * 100, 2
            ),
            "auto_classified_count": review_counts["auto_classified"],
            "coverage_percent": round(operating["coverage"] * 100, 2),
            "fixture_case_count": evaluation["fixture_case_count"],
            "human_review_count": review_counts["human_review_required"],
            "macro_f1": operating["macro_f1_with_abstentions_as_false_negatives"],
            "modeled_cost_usd": costs["usage"]["modeled_total_cost_usd"],
            "operating_threshold": evaluation["operating_confidence_threshold"],
            "provider": evaluation["prompt_metadata"]["provider"],
            "realized_cost_or_savings_claimed": costs["usage"][
                "realized_cost_or_savings_claimed"
            ],
        },
        "incidents": {
            "failure_type_counts": incident_summary["failure_type_counts"],
            "open_count": incident_summary["open_incident_count"],
            "resolved_count": incident_summary["lifecycle_counts"].get(
                "resolved", 0
            ),
            "rows": incident_rows,
            "severity_counts": severity_counts,
            "total_count": incident_summary["incident_count"],
        },
        "monitoring": {
            "check_count": monitoring["check_count"],
            "degraded_count": outcome_counts.get("degraded", 0),
            "healthy_count": outcome_counts.get("healthy", 0),
            "healthy_percent": _percentage(
                outcome_counts.get("healthy", 0), monitoring["check_count"]
            ),
            "run_count": monitoring["run_count"],
            "services": services,
            "target_count": monitoring["target_count"],
            "unhealthy_count": outcome_counts.get("unhealthy", 0),
        },
        "provenance": {
            "as_of": observed_at,
            "data_classification": "Synthetic portfolio fixtures",
            "external_api_called": evaluation["prompt_metadata"][
                "external_api_called"
            ],
            "source": "public-apis excerpt plus deterministic operational fixtures",
        },
        "registry": {
            "api_count": registry_summary["api_count"],
            "category_counts": registry_summary["category_counts"],
            "eligible_count": registry_summary["monitoring_eligible_count"],
            "eligible_percent": _percentage(
                registry_summary["monitoring_eligible_count"],
                registry_summary["api_count"],
            ),
        },
    }


def write_dashboard_payload(
    output_path: Path = DEFAULT_OUTPUT,
    artifacts_directory: Path = DEFAULT_ARTIFACTS,
) -> dict[str, object]:
    payload = build_dashboard_payload(artifacts_directory)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    payload = write_dashboard_payload(arguments.output, arguments.artifacts)
    print(
        json.dumps(
            {
                "dashboard_output": str(arguments.output),
                "incident_count": payload["incidents"]["total_count"],
                "service_count": payload["monitoring"]["target_count"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
