from pathlib import Path
import tempfile
import unittest

from api_support_operations.catalog import parse_catalog, summarize_registry
from api_support_operations.pipeline import build_registry


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY_ROOT / "data" / "public_apis_excerpt.md"


class CatalogParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.markdown = FIXTURE.read_text(encoding="utf-8")
        self.records = parse_catalog(self.markdown)

    def test_fixture_builds_expected_registry(self) -> None:
        self.assertEqual(len(self.records), 12)
        self.assertEqual(
            [record.api_id for record in self.records],
            [
                "art-design-art-institute-of-chicago",
                "art-design-metropolitan-museum-of-art",
                "transportation-transitland",
                "transportation-transport-for-belgium",
                "transportation-transport-for-london-england",
                "transportation-transport-rest",
                "vehicle-nhtsa",
                "vehicle-problemsbyvin",
                "weather-open-meteo",
                "weather-pirate-weather",
                "weather-us-weather",
                "weather-weatherstack",
            ],
        )

    def test_normalization_and_monitoring_eligibility(self) -> None:
        records_by_name = {record.name: record for record in self.records}
        self.assertEqual(records_by_name["Weatherstack"].auth_type, "api_key")
        self.assertFalse(records_by_name["Weatherstack"].monitoring_eligible)
        self.assertEqual(records_by_name["TransitLand"].cors_status, "unknown")
        self.assertTrue(records_by_name["Open-Meteo"].https_supported)
        self.assertTrue(records_by_name["Open-Meteo"].monitoring_eligible)

    def test_summary_is_stable_and_decision_oriented(self) -> None:
        self.assertEqual(
            summarize_registry(self.records),
            {
                "api_count": 12,
                "monitoring_eligible_count": 10,
                "category_counts": {
                    "Art & Design": 2,
                    "Transportation": 4,
                    "Vehicle": 2,
                    "Weather": 4,
                },
                "auth_type_counts": {"api_key": 2, "none": 10},
            },
        )

    def test_duplicate_names_receive_deterministic_suffixes(self) -> None:
        duplicate_fixture = """
### Weather
API | Description | Auth | HTTPS | CORS
|:---|:---|:---|:---|:---|
| [Example](https://example.com/one) | One | No | Yes | Yes |
| [Example](https://example.com/two) | Two | No | Yes | Yes |
"""
        records = parse_catalog(duplicate_fixture)
        self.assertEqual(
            [record.api_id for record in records],
            ["weather-example", "weather-example-2"],
        )

    def test_pipeline_outputs_are_byte_for_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_directory = Path(first)
            second_directory = Path(second)
            build_registry(FIXTURE, first_directory)
            build_registry(FIXTURE, second_directory)

            for filename in (
                "api_registry.csv",
                "api_registry.json",
                "registry_summary.json",
            ):
                self.assertEqual(
                    (first_directory / filename).read_bytes(),
                    (second_directory / filename).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()

