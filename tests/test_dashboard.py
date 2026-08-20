from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from api_support_operations.dashboard import (
    build_dashboard_payload,
    write_dashboard_payload,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPOSITORY_ROOT / "artifacts"
SITE = REPOSITORY_ROOT / "site"
DASHBOARD_DATA = SITE / "data" / "dashboard.json"


class DashboardDataTests(unittest.TestCase):
    def test_payload_reconciles_upstream_artifacts(self) -> None:
        payload = build_dashboard_payload(ARTIFACTS)

        self.assertEqual(payload["registry"]["api_count"], 12)
        self.assertEqual(payload["registry"]["eligible_count"], 10)
        self.assertEqual(payload["monitoring"]["check_count"], 21)
        self.assertEqual(payload["monitoring"]["target_count"], 3)
        self.assertEqual(payload["incidents"]["total_count"], 6)
        self.assertEqual(len(payload["incidents"]["rows"]), 6)
        self.assertEqual(payload["ai_evaluation"]["coverage_percent"], 90.91)
        self.assertEqual(payload["ai_evaluation"]["macro_f1"], 0.96)
        self.assertFalse(
            payload["ai_evaluation"]["realized_cost_or_savings_claimed"]
        )

    def test_dashboard_data_is_byte_for_byte_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_path = Path(first) / "dashboard.json"
            second_path = Path(second) / "dashboard.json"
            write_dashboard_payload(first_path, ARTIFACTS)
            write_dashboard_payload(second_path, ARTIFACTS)
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())

    def test_tracked_dashboard_data_matches_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "dashboard.json"
            write_dashboard_payload(generated, ARTIFACTS)
            self.assertEqual(DASHBOARD_DATA.read_bytes(), generated.read_bytes())

    def test_static_site_exposes_decisions_and_limitations(self) -> None:
        html = (SITE / "index.html").read_text(encoding="utf-8")
        script = (SITE / "app.js").read_text(encoding="utf-8")
        payload = json.loads(DASHBOARD_DATA.read_text(encoding="utf-8"))

        self.assertIn("Executive operations brief", html)
        self.assertIn("Incident decision queue", html)
        self.assertIn("Synthetic portfolio fixtures", html)
        self.assertIn("modeled—not realized", html)
        self.assertIn("textContent", script)
        self.assertNotIn("innerHTML", script)
        self.assertEqual(payload["provenance"]["data_classification"], "Synthetic portfolio fixtures")


if __name__ == "__main__":
    unittest.main()
