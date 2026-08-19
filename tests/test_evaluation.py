from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from api_support_operations.classification import (
    ClassificationConfigurationError,
    DeterministicIncidentClassifier,
    load_classification_configuration,
)
from api_support_operations.evaluation import evaluate_classifier, load_evaluation_cases
from api_support_operations.evaluation_pipeline import build_evaluation_artifacts


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPOSITORY_ROOT / "config" / "classification_policy.json"
FIXTURES = REPOSITORY_ROOT / "data" / "classification_evaluation.json"
INCIDENTS = REPOSITORY_ROOT / "artifacts" / "incidents.json"
ARTIFACTS = REPOSITORY_ROOT / "artifacts"
DAY_4_ARTIFACTS = (
    "classification_cost_summary.json",
    "classification_evaluation.json",
    "incident_classifications.json",
)


class StepTimer:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        self.value += 250_000
        return self.value


class ClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configuration = load_classification_configuration(CONFIG)
        cls.classifier = DeterministicIncidentClassifier(cls.configuration)
        cls.cases = load_evaluation_cases(FIXTURES)

    def test_committed_fixtures_are_synthetic_and_cover_all_outcomes(self) -> None:
        payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
        categories = {
            case["expected"]["failure_category"] for case in payload["cases"]
        }
        review_states = {case["expected"]["review_state"] for case in payload["cases"]}

        self.assertIn("synthetic", payload["data_classification"].lower())
        self.assertEqual(
            categories,
            {
                "authentication_failure",
                "availability",
                "latency_degradation",
                "rate_limiting",
                "schema_drift",
                "unknown",
            },
        )
        self.assertEqual(
            review_states,
            {"auto_classified", "human_review_required"},
        )

    def test_baseline_classifies_required_fields_and_abstains_when_ambiguous(self) -> None:
        predictions = [self.classifier.classify(case.incident) for case in self.cases]
        ambiguous = next(
            item for item in predictions if item.incident_id == "eval-abstention"
        )
        low_confidence = next(
            item for item in predictions if item.incident_id == "eval-low-confidence"
        )

        self.assertEqual(ambiguous.failure_category, "unknown")
        self.assertEqual(ambiguous.priority, "UNASSESSED")
        self.assertEqual(ambiguous.recommended_owner, "Human triage")
        self.assertEqual(ambiguous.review_state, "human_review_required")
        self.assertIn("no supported failure signal", ambiguous.abstention_reason)
        self.assertEqual(low_confidence.failure_category, "availability")
        self.assertEqual(low_confidence.review_state, "human_review_required")
        self.assertTrue(all(item.summary for item in predictions))

    def test_metadata_and_usage_are_transparent_and_offline(self) -> None:
        prediction = self.classifier.classify(self.cases[0].incident)

        self.assertFalse(prediction.prompt_metadata.external_api_called)
        self.assertEqual(len(prediction.prompt_metadata.prompt_template_sha256), 64)
        self.assertEqual(prediction.prompt_metadata.prompt_version, "incident-triage-v1")
        self.assertGreater(prediction.modeled_usage.input_tokens, 0)
        self.assertGreater(prediction.modeled_usage.output_tokens, 0)
        self.assertIn("Modeled only", prediction.modeled_usage.basis)
        self.assertGreater(float(prediction.modeled_usage.total_cost_usd), 0)

    def test_configuration_rejects_costs_not_labeled_as_modeled(self) -> None:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
        payload["modeled_pricing"]["basis"] = "Actual provider invoice."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ClassificationConfigurationError,
                "explicitly labeled modeled only",
            ):
                load_classification_configuration(path)


class EvaluationMetricTests(unittest.TestCase):
    def test_accuracy_macro_f1_per_class_thresholds_latency_and_cost(self) -> None:
        configuration = load_classification_configuration(CONFIG)
        classifier = DeterministicIncidentClassifier(configuration)
        cases = load_evaluation_cases(FIXTURES)

        report, predictions = evaluate_classifier(
            classifier,
            cases,
            timer_ns=StepTimer(),
        )
        operating = next(
            item for item in report["threshold_analysis"] if item["threshold"] == 0.85
        )

        self.assertEqual(len(predictions), 12)
        self.assertEqual(report["field_accuracy"]["failure_category"], 1.0)
        self.assertEqual(operating["accuracy_on_answered"], 1.0)
        self.assertEqual(operating["coverage"], 0.9091)
        self.assertEqual(operating["abstention_rate"], 0.0909)
        self.assertEqual(operating["macro_f1_with_abstentions_as_false_negatives"], 0.96)
        self.assertEqual(set(operating["per_class"]), {
            "authentication_failure",
            "availability",
            "latency_degradation",
            "rate_limiting",
            "schema_drift",
        })
        self.assertEqual(report["latency"]["p95_bucket"], "<1 ms")
        self.assertFalse(
            report["modeled_usage_and_cost"]["realized_cost_or_savings_claimed"]
        )

    def test_higher_threshold_reduces_coverage_and_macro_f1(self) -> None:
        configuration = load_classification_configuration(CONFIG)
        report, _ = evaluate_classifier(
            DeterministicIncidentClassifier(configuration),
            load_evaluation_cases(FIXTURES),
            timer_ns=StepTimer(),
        )
        by_threshold = {
            item["threshold"]: item for item in report["threshold_analysis"]
        }

        self.assertGreater(by_threshold[0.85]["coverage"], by_threshold[0.95]["coverage"])
        self.assertGreater(
            by_threshold[0.85]["macro_f1_with_abstentions_as_false_negatives"],
            by_threshold[0.95]["macro_f1_with_abstentions_as_false_negatives"],
        )


class EvaluationPipelineTests(unittest.TestCase):
    def test_outputs_are_byte_for_byte_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_path = Path(first)
            second_path = Path(second)
            first_summary = build_evaluation_artifacts(
                CONFIG,
                FIXTURES,
                INCIDENTS,
                first_path,
                timer_ns=StepTimer(),
            )
            second_summary = build_evaluation_artifacts(
                CONFIG,
                FIXTURES,
                INCIDENTS,
                second_path,
                timer_ns=StepTimer(),
            )

            self.assertEqual(first_summary, second_summary)
            self.assertEqual(first_summary["classification_count"], 6)
            for filename in DAY_4_ARTIFACTS:
                self.assertEqual(
                    (first_path / filename).read_bytes(),
                    (second_path / filename).read_bytes(),
                    filename,
                )

    def test_tracked_artifacts_match_full_day_4_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory)
            build_evaluation_artifacts(
                CONFIG,
                FIXTURES,
                INCIDENTS,
                generated,
                timer_ns=StepTimer(),
            )
            for filename in DAY_4_ARTIFACTS:
                self.assertEqual(
                    (ARTIFACTS / filename).read_bytes(),
                    (generated / filename).read_bytes(),
                    filename,
                )


if __name__ == "__main__":
    unittest.main()
