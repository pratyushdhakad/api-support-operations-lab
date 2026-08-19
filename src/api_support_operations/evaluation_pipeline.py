"""Build Day 4 incident classifications and reproducible evaluation artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter_ns
from typing import Callable

from .classification import (
    DeterministicIncidentClassifier,
    classification_input_from_incident,
    load_classification_configuration,
)
from .evaluation import (
    DEFAULT_THRESHOLDS,
    evaluate_classifier,
    load_evaluation_cases,
    summarize_modeled_usage,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPOSITORY_ROOT / "config" / "classification_policy.json"
DEFAULT_FIXTURES = REPOSITORY_ROOT / "data" / "classification_evaluation.json"
DEFAULT_INCIDENTS = REPOSITORY_ROOT / "artifacts" / "incidents.json"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_incidents(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Incident artifact must be a list")
    return payload


def build_evaluation_artifacts(
    config_path: Path,
    fixtures_path: Path,
    incidents_path: Path,
    output_directory: Path,
    *,
    timer_ns: Callable[[], int] = perf_counter_ns,
) -> dict[str, object]:
    configuration = load_classification_configuration(config_path)
    classifier = DeterministicIncidentClassifier(configuration)
    incidents = _load_incidents(incidents_path)
    classifications = [
        classifier.classify(classification_input_from_incident(incident))
        for incident in incidents
    ]
    cases = load_evaluation_cases(fixtures_path)
    report, _ = evaluate_classifier(
        classifier,
        cases,
        thresholds=DEFAULT_THRESHOLDS,
        timer_ns=timer_ns,
    )
    operating_point = next(
        item
        for item in report["threshold_analysis"]
        if item["threshold"] == configuration.operating_confidence_threshold
    )
    report["operating_confidence_threshold"] = configuration.operating_confidence_threshold
    report["operating_point"] = operating_point

    pricing = configuration.pricing
    cost_summary = {
        "modeled_pricing": {
            "basis": pricing.basis,
            "currency": pricing.currency,
            "input_usd_per_million_tokens": str(pricing.input_usd_per_million_tokens),
            "name": pricing.name,
            "output_usd_per_million_tokens": str(pricing.output_usd_per_million_tokens),
        },
        "scope": "Committed synthetic Day 3 incidents classified by the offline baseline.",
        "usage": summarize_modeled_usage(classifications),
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_json(
        output_directory / "incident_classifications.json",
        [item.to_dict() for item in classifications],
    )
    _write_json(output_directory / "classification_evaluation.json", report)
    _write_json(output_directory / "classification_cost_summary.json", cost_summary)
    return {
        "classification_count": len(classifications),
        "evaluation_case_count": len(cases),
        "modeled_total_cost_usd": cost_summary["usage"]["modeled_total_cost_usd"],
        "operating_accuracy_on_answered": operating_point["accuracy_on_answered"],
        "operating_coverage": operating_point["coverage"],
        "operating_macro_f1": operating_point[
            "macro_f1_with_abstentions_as_false_negatives"
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--incidents", type=Path, default=DEFAULT_INCIDENTS)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    arguments = parser.parse_args()
    summary = build_evaluation_artifacts(
        arguments.config,
        arguments.fixtures,
        arguments.incidents,
        arguments.output_directory,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
