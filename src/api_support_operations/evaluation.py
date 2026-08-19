"""Reproducible evaluation metrics for incident classifier implementations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
from time import perf_counter_ns
from typing import Callable, Iterable, Mapping

from .classification import (
    FAILURE_CATEGORIES,
    ClassificationInput,
    IncidentClassification,
    IncidentClassifier,
)


OPERATIONAL_CATEGORIES = FAILURE_CATEGORIES[:-1]
DEFAULT_THRESHOLDS = (0.0, 0.70, 0.85, 0.95)


@dataclass(frozen=True)
class EvaluationCase:
    incident: ClassificationInput
    expected: Mapping[str, str]


def load_evaluation_cases(path: Path) -> tuple[EvaluationCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported evaluation fixture schema")
    if "synthetic" not in str(payload.get("data_classification", "")).lower():
        raise ValueError("Evaluation fixture must be explicitly labeled synthetic")
    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    for raw in payload.get("cases", []):
        incident = ClassificationInput(**raw["input"])
        expected = {str(key): str(value) for key, value in raw["expected"].items()}
        if incident.incident_id in seen:
            raise ValueError(f"Duplicate evaluation case: {incident.incident_id}")
        if expected.get("failure_category") not in FAILURE_CATEGORIES:
            raise ValueError(f"Unsupported fixture category: {incident.incident_id}")
        seen.add(incident.incident_id)
        cases.append(EvaluationCase(incident, expected))
    if not cases:
        raise ValueError("At least one evaluation case is required")
    return tuple(cases)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _intrinsically_answerable(prediction: IncidentClassification) -> bool:
    return (
        prediction.failure_category != "unknown"
        and prediction.priority != "UNASSESSED"
        and prediction.recommended_owner != "Human triage"
    )


def _per_class_metrics(
    cases: tuple[EvaluationCase, ...],
    predictions: tuple[IncidentClassification, ...],
    threshold: float,
) -> dict[str, dict[str, float | int]]:
    metrics: dict[str, dict[str, float | int]] = {}
    for category in OPERATIONAL_CATEGORIES:
        true_positives = false_positives = false_negatives = answered = support = 0
        for case, prediction in zip(cases, predictions):
            expected = case.expected["failure_category"]
            if expected not in OPERATIONAL_CATEGORIES:
                continue
            is_answered = (
                _intrinsically_answerable(prediction)
                and prediction.confidence >= threshold
            )
            if expected == category:
                support += 1
                if is_answered:
                    answered += 1
                    if prediction.failure_category == category:
                        true_positives += 1
                    else:
                        false_negatives += 1
                else:
                    false_negatives += 1
            elif is_answered and prediction.failure_category == category:
                false_positives += 1
        precision = _ratio(true_positives, true_positives + false_positives)
        recall = _ratio(true_positives, true_positives + false_negatives)
        f1 = _ratio(
            2 * true_positives,
            2 * true_positives + false_positives + false_negatives,
        )
        metrics[category] = {
            "answered": answered,
            "f1": f1,
            "precision": precision,
            "recall": recall,
            "support": support,
        }
    return metrics


def _threshold_report(
    cases: tuple[EvaluationCase, ...],
    predictions: tuple[IncidentClassification, ...],
    threshold: float,
) -> dict[str, object]:
    scorable = [
        (case, prediction)
        for case, prediction in zip(cases, predictions)
        if case.expected["failure_category"] in OPERATIONAL_CATEGORIES
    ]
    answered = [
        (case, prediction)
        for case, prediction in scorable
        if _intrinsically_answerable(prediction) and prediction.confidence >= threshold
    ]
    correct = sum(
        case.expected["failure_category"] == prediction.failure_category
        for case, prediction in answered
    )
    per_class = _per_class_metrics(cases, predictions, threshold)
    macro_f1 = round(
        sum(float(values["f1"]) for values in per_class.values()) / len(per_class),
        4,
    )
    return {
        "abstention_rate": _ratio(len(scorable) - len(answered), len(scorable)),
        "accuracy_on_answered": _ratio(correct, len(answered)),
        "answered_count": len(answered),
        "coverage": _ratio(len(answered), len(scorable)),
        "macro_f1_with_abstentions_as_false_negatives": macro_f1,
        "overall_accuracy_with_abstentions_as_incorrect": _ratio(correct, len(scorable)),
        "per_class": per_class,
        "scorable_count": len(scorable),
        "threshold": threshold,
    }


def _latency_bucket(milliseconds: float) -> str:
    if milliseconds < 1:
        return "<1 ms"
    if milliseconds < 5:
        return "1-<5 ms"
    if milliseconds < 20:
        return "5-<20 ms"
    if milliseconds < 100:
        return "20-<100 ms"
    return ">=100 ms"


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _field_accuracy(
    cases: tuple[EvaluationCase, ...],
    predictions: tuple[IncidentClassification, ...],
) -> dict[str, float]:
    mappings = {
        "failure_category": lambda item: item.failure_category,
        "priority": lambda item: item.priority,
        "recommended_owner": lambda item: item.recommended_owner,
        "review_state": lambda item: item.review_state,
        "summary": lambda item: item.summary,
    }
    return {
        field: _ratio(
            sum(case.expected[field] == getter(prediction) for case, prediction in zip(cases, predictions)),
            len(cases),
        )
        for field, getter in mappings.items()
    }


def summarize_modeled_usage(
    predictions: Iterable[IncidentClassification],
) -> dict[str, object]:
    items = tuple(predictions)
    total_input_tokens = sum(item.modeled_usage.input_tokens for item in items)
    total_output_tokens = sum(item.modeled_usage.output_tokens for item in items)
    total_cost = sum(Decimal(item.modeled_usage.total_cost_usd) for item in items)
    return {
        "basis": items[0].modeled_usage.basis,
        "currency": items[0].modeled_usage.currency,
        "modeled_input_tokens": total_input_tokens,
        "modeled_output_tokens": total_output_tokens,
        "modeled_total_cost_usd": str(total_cost.quantize(Decimal("0.00000001"))),
        "request_count": len(items),
        "realized_cost_or_savings_claimed": False,
    }


def evaluate_classifier(
    classifier: IncidentClassifier,
    cases: tuple[EvaluationCase, ...],
    *,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    timer_ns: Callable[[], int] = perf_counter_ns,
) -> tuple[dict[str, object], tuple[IncidentClassification, ...]]:
    predictions: list[IncidentClassification] = []
    durations_ms: list[float] = []
    for case in cases:
        started = timer_ns()
        prediction = classifier.classify(case.incident)
        finished = timer_ns()
        predictions.append(prediction)
        durations_ms.append(max(0, finished - started) / 1_000_000)
    prediction_tuple = tuple(predictions)
    review_counts = Counter(item.review_state for item in prediction_tuple)
    report = {
        "evaluation_contract": {
            "category_metrics_scope": "Known operational categories only; unknown labels test abstention behavior.",
            "fixture_type": "committed synthetic labeled cases",
            "latency_reporting": "Observed local wall-clock classifier duration, bucketed for reproducible artifacts; not a service-level claim.",
        },
        "field_accuracy": _field_accuracy(cases, prediction_tuple),
        "fixture_case_count": len(cases),
        "latency": {
            "measurement": "observed_local_wall_clock",
            "p50_bucket": _latency_bucket(_percentile(durations_ms, 0.50)),
            "p95_bucket": _latency_bucket(_percentile(durations_ms, 0.95)),
            "reporting": "bucketed_for_reproducibility",
            "sample_count": len(durations_ms),
        },
        "modeled_usage_and_cost": summarize_modeled_usage(prediction_tuple),
        "prompt_metadata": as_prompt_metadata(prediction_tuple[0]),
        "review_state_counts": dict(sorted(review_counts.items())),
        "threshold_analysis": [
            _threshold_report(cases, prediction_tuple, threshold)
            for threshold in thresholds
        ],
    }
    return report, prediction_tuple


def as_prompt_metadata(prediction: IncidentClassification) -> dict[str, object]:
    metadata = prediction.prompt_metadata
    return {
        "classifier_version": metadata.classifier_version,
        "external_api_called": metadata.external_api_called,
        "model": metadata.model,
        "prompt_template_sha256": metadata.prompt_template_sha256,
        "prompt_version": metadata.prompt_version,
        "provider": metadata.provider,
    }
