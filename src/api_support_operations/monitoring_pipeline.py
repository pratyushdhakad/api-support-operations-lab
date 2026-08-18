"""Build deterministic Day 2 monitoring artifacts or run an explicit live probe."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Mapping

from .catalog import parse_catalog
from .monitoring import (
    HealthCheckEngine,
    HealthCheckResult,
    MonitoringConfiguration,
    TransportResponse,
    UrllibTransport,
    load_monitoring_configuration,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPOSITORY_ROOT / "config" / "monitoring_targets.json"
DEFAULT_FIXTURES = REPOSITORY_ROOT / "data" / "mock_health_runs.json"
DEFAULT_REGISTRY_SOURCE = REPOSITORY_ROOT / "data" / "public_apis_excerpt.md"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts"
DEFAULT_RUNTIME_DIRECTORY = REPOSITORY_ROOT / "runtime"
CSV_FIELDS = (
    "run_id",
    "observed_at",
    "api_id",
    "endpoint",
    "status_code",
    "latency_ms",
    "outcome",
    "error_type",
    "error_detail",
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class FixtureClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, milliseconds: int) -> None:
        self.value += milliseconds / 1000


class FixtureTransport:
    """Deterministic transport whose scenarios never touch the network."""

    def __init__(self, responses: Mapping[str, object], clock: FixtureClock) -> None:
        self.responses = responses
        self.clock = clock

    def request(
        self,
        *,
        url: str,
        method: str,
        timeout_seconds: float,
        headers: Mapping[str, str],
    ) -> TransportResponse:
        scenario = next(
            value
            for value in self.responses.values()
            if isinstance(value, dict) and value.get("endpoint") == url
        )
        self.clock.advance(int(scenario["latency_ms"]))
        error_type = scenario.get("error_type")
        if error_type == "timeout":
            raise TimeoutError("deterministic fixture timeout")
        if error_type == "dns_error":
            raise OSError("deterministic fixture DNS error")
        if error_type:
            raise RuntimeError(f"deterministic fixture {error_type}")
        return TransportResponse(
            int(scenario["status_code"]),
            {"Content-Type": str(scenario["content_type"])},
        )


def _eligible_ids(registry_source: Path) -> set[str]:
    records = parse_catalog(registry_source.read_text(encoding="utf-8"))
    return {record.api_id for record in records if record.monitoring_eligible}


def _attach_endpoints(responses: dict[str, object], configuration: object) -> dict[str, object]:
    targets = {target.api_id: target.endpoint for target in configuration.targets}
    enriched: dict[str, object] = {}
    for api_id, raw_scenario in responses.items():
        if api_id not in targets or not isinstance(raw_scenario, dict):
            raise ValueError(f"Unknown or invalid fixture target: {api_id}")
        enriched[api_id] = {**raw_scenario, "endpoint": targets[api_id]}
    if set(enriched) != set(targets):
        raise ValueError("Each fixture run must cover every configured target")
    return enriched


def _build_history(results: list[HealthCheckResult]) -> list[dict[str, object]]:
    grouped: defaultdict[str, list[HealthCheckResult]] = defaultdict(list)
    for result in results:
        grouped[result.api_id].append(result)
    history = []
    for api_id in sorted(grouped):
        samples = grouped[api_id]
        history.append(
            {
                "api_id": api_id,
                "endpoint": samples[0].endpoint,
                "sample_count": len(samples),
                "average_latency_ms": round(
                    sum(sample.latency_ms for sample in samples) / len(samples), 1
                ),
                "samples": [
                    {
                        "error_type": sample.error_type,
                        "latency_ms": sample.latency_ms,
                        "observed_at": sample.observed_at,
                        "outcome": sample.outcome,
                        "status_code": sample.status_code,
                    }
                    for sample in samples
                ],
            }
        )
    return history


def _build_summary(results: list[HealthCheckResult]) -> dict[str, object]:
    outcome_counts = Counter(result.outcome for result in results)
    error_counts = Counter(result.error_type for result in results if result.error_type)
    latest = {result.api_id: result.outcome for result in results}
    return {
        "check_count": len(results),
        "error_type_counts": dict(sorted(error_counts.items())),
        "latest_outcomes": dict(sorted(latest.items())),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "run_count": len({result.run_id for result in results}),
        "target_count": len({result.api_id for result in results}),
    }


def _write_csv(path: Path, results: list[HealthCheckResult]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for result in results:
            row = result.to_dict()
            writer.writerow({key: "" if value is None else value for key, value in row.items()})


def build_fixture_artifacts(
    config_path: Path,
    fixture_path: Path,
    registry_source: Path,
    output_directory: Path,
) -> dict[str, object]:
    configuration = load_monitoring_configuration(
        config_path,
        monitoring_eligible_api_ids=_eligible_ids(registry_source),
    )
    fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixture_payload.get("schema_version") != 1:
        raise ValueError("Unsupported monitoring fixture schema")
    results: list[HealthCheckResult] = []
    for fixture_run in fixture_payload.get("runs", []):
        clock = FixtureClock()
        responses = _attach_endpoints(fixture_run["responses"], configuration)
        engine = HealthCheckEngine(
            configuration,
            FixtureTransport(responses, clock),
            monotonic=clock,
        )
        results.extend(
            engine.run(
                run_id=str(fixture_run["run_id"]),
                observed_at=str(fixture_run["observed_at"]),
            )
        )
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_csv(output_directory / "health_check_history.csv", results)
    _write_json(output_directory / "health_check_results.json", [result.to_dict() for result in results])
    _write_json(output_directory / "latency_history.json", _build_history(results))
    summary = _build_summary(results)
    _write_json(output_directory / "monitoring_summary.json", summary)
    return summary


def enforce_live_interval(
    configuration: MonitoringConfiguration,
    output_directory: Path,
    now: datetime,
) -> None:
    """Refuse a live run when this runtime history contains a recent observation."""

    latest: datetime | None = None
    for result_path in output_directory.glob("live-*.json"):
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        for result in payload:
            observed_at = datetime.fromisoformat(
                str(result["observed_at"]).replace("Z", "+00:00")
            )
            latest = observed_at if latest is None else max(latest, observed_at)
    if latest is None:
        return

    minimum_seconds = configuration.policy.minimum_interval_minutes * 60
    elapsed_seconds = (now - latest).total_seconds()
    if elapsed_seconds < minimum_seconds:
        remaining_minutes = max(1, round((minimum_seconds - elapsed_seconds) / 60))
        raise RuntimeError(
            "Live run blocked by the configured minimum interval; "
            f"try again in approximately {remaining_minutes} minute(s)"
        )


def run_live(config_path: Path, registry_source: Path, output_directory: Path) -> dict[str, object]:
    configuration = load_monitoring_configuration(
        config_path,
        monitoring_eligible_api_ids=_eligible_ids(registry_source),
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    enforce_live_interval(configuration, output_directory, now)
    run_id = now.strftime("live-%Y%m%d-%H%M%S")
    results = HealthCheckEngine(configuration, UrllibTransport()).run(
        run_id=run_id,
        observed_at=now.isoformat().replace("+00:00", "Z"),
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_json(output_directory / f"{run_id}.json", [result.to_dict() for result in results])
    return _build_summary(results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--registry-source", type=Path, default=DEFAULT_REGISTRY_SOURCE)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly perform one request per reviewed target; never used by tests or make run",
    )
    arguments = parser.parse_args()
    if arguments.live:
        summary = run_live(
            arguments.config,
            arguments.registry_source,
            arguments.output_directory or DEFAULT_RUNTIME_DIRECTORY,
        )
    else:
        summary = build_fixture_artifacts(
            arguments.config,
            arguments.fixtures,
            arguments.registry_source,
            arguments.output_directory or DEFAULT_OUTPUT_DIRECTORY,
        )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
