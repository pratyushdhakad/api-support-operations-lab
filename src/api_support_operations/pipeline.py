"""Generate deterministic API registry artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .catalog import ApiRecord, parse_catalog, summarize_registry


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPOSITORY_ROOT / "data" / "public_apis_excerpt.md"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts"
CSV_FIELDS = (
    "api_id",
    "category",
    "name",
    "description",
    "documentation_url",
    "auth_type",
    "https_supported",
    "cors_status",
    "monitoring_eligible",
    "source_line",
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _csv_value(value: object) -> object:
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "unknown"
    return value


def write_registry_csv(path: Path, records: list[ApiRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow(
                {key: _csv_value(value) for key, value in record.to_dict().items()}
            )


def build_registry(source: Path, output_directory: Path) -> dict[str, object]:
    records = parse_catalog(source.read_text(encoding="utf-8"))
    if not records:
        raise ValueError(f"No API records found in {source}")

    output_directory.mkdir(parents=True, exist_ok=True)
    registry_payload = [record.to_dict() for record in records]
    summary = summarize_registry(records)
    write_registry_csv(output_directory / "api_registry.csv", records)
    _write_json(output_directory / "api_registry.json", registry_payload)
    _write_json(output_directory / "registry_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    arguments = parser.parse_args()
    summary = build_registry(arguments.source, arguments.output_directory)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

