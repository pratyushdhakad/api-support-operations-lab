"""Controlled HTTP health checks with explicit policy and failure taxonomy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import socket
import ssl
import time
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


ERROR_TYPES = (
    "connection_error",
    "dns_error",
    "http_status",
    "response_contract",
    "timeout",
    "tls_error",
    "unexpected_error",
)


class MonitoringConfigurationError(ValueError):
    """Raised when a target configuration violates monitoring guardrails."""


@dataclass(frozen=True)
class MonitoringPolicy:
    user_agent: str
    max_targets_per_run: int
    minimum_interval_minutes: int
    default_timeout_seconds: float
    maximum_timeout_seconds: float
    catalog_inclusion_authorizes_requests: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class MonitoringTarget:
    api_id: str
    name: str
    endpoint: str
    method: str
    timeout_seconds: float
    expected_statuses: tuple[int, ...]
    expected_content_type: str
    documentation_url: str
    policy_review_status: str
    reviewed_on: str
    live_monitoring_enabled: bool
    policy_notes: tuple[str, ...]


@dataclass(frozen=True)
class MonitoringConfiguration:
    schema_version: int
    policy: MonitoringPolicy
    targets: tuple[MonitoringTarget, ...]


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: Mapping[str, str]


class HttpTransport(Protocol):
    def request(
        self,
        *,
        url: str,
        method: str,
        timeout_seconds: float,
        headers: Mapping[str, str],
    ) -> TransportResponse:
        """Make one request or raise a network exception."""


@dataclass(frozen=True)
class HealthCheckResult:
    run_id: str
    observed_at: str
    api_id: str
    endpoint: str
    status_code: int | None
    latency_ms: int
    outcome: str
    error_type: str | None
    error_detail: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MonitoringConfigurationError(message)


def load_monitoring_configuration(
    path: Path,
    *,
    monitoring_eligible_api_ids: set[str] | None = None,
) -> MonitoringConfiguration:
    """Load and validate the explicit monitoring allowlist."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(payload.get("schema_version") == 1, "Unsupported monitoring schema")
    raw_policy = payload.get("policy", {})
    policy = MonitoringPolicy(
        user_agent=str(raw_policy.get("user_agent", "")),
        max_targets_per_run=int(raw_policy.get("max_targets_per_run", 0)),
        minimum_interval_minutes=int(raw_policy.get("minimum_interval_minutes", 0)),
        default_timeout_seconds=float(raw_policy.get("default_timeout_seconds", 0)),
        maximum_timeout_seconds=float(raw_policy.get("maximum_timeout_seconds", 0)),
        catalog_inclusion_authorizes_requests=bool(
            raw_policy.get("catalog_inclusion_authorizes_requests", True)
        ),
        notes=tuple(str(note) for note in raw_policy.get("notes", [])),
    )
    _require(
        policy.catalog_inclusion_authorizes_requests is False,
        "Catalog inclusion must not authorize requests",
    )
    _require("api-support-operations-lab" in policy.user_agent, "User agent must identify the project")
    _require("contact:" in policy.user_agent, "User agent must provide a contact route")
    _require(1 <= policy.max_targets_per_run <= 10, "Target budget must be between 1 and 10")
    _require(policy.minimum_interval_minutes >= 60, "Minimum interval must be at least 60 minutes")
    _require(
        0 < policy.default_timeout_seconds <= policy.maximum_timeout_seconds <= 10,
        "Timeout policy must be bounded at 10 seconds",
    )

    targets: list[MonitoringTarget] = []
    seen_ids: set[str] = set()
    for raw_target in payload.get("targets", []):
        target = MonitoringTarget(
            api_id=str(raw_target.get("api_id", "")),
            name=str(raw_target.get("name", "")),
            endpoint=str(raw_target.get("endpoint", "")),
            method=str(raw_target.get("method", "")),
            timeout_seconds=float(
                raw_target.get("timeout_seconds", policy.default_timeout_seconds)
            ),
            expected_statuses=tuple(int(value) for value in raw_target.get("expected_statuses", [])),
            expected_content_type=str(raw_target.get("expected_content_type", "")),
            documentation_url=str(raw_target.get("documentation_url", "")),
            policy_review_status=str(raw_target.get("policy_review_status", "")),
            reviewed_on=str(raw_target.get("reviewed_on", "")),
            live_monitoring_enabled=bool(raw_target.get("live_monitoring_enabled", False)),
            policy_notes=tuple(str(note) for note in raw_target.get("policy_notes", [])),
        )
        parsed_endpoint = urlsplit(target.endpoint)
        _require(target.api_id not in seen_ids, f"Duplicate target: {target.api_id}")
        _require(target.method == "GET", f"Only GET is allowed: {target.api_id}")
        _require(
            parsed_endpoint.scheme == "https" and bool(parsed_endpoint.netloc),
            f"Target must use an exact HTTPS endpoint: {target.api_id}",
        )
        _require(not parsed_endpoint.username, f"Endpoint must not contain credentials: {target.api_id}")
        _require(not parsed_endpoint.fragment, f"Endpoint must not contain a fragment: {target.api_id}")
        _require(
            0 < target.timeout_seconds <= policy.maximum_timeout_seconds,
            f"Timeout exceeds policy: {target.api_id}",
        )
        _require(target.expected_statuses, f"Expected status is required: {target.api_id}")
        _require(target.expected_content_type, f"Expected content type is required: {target.api_id}")
        _require(target.policy_review_status == "reviewed", f"Target is not reviewed: {target.api_id}")
        _require(bool(target.reviewed_on), f"Review date is required: {target.api_id}")
        _require(len(target.policy_notes) >= 2, f"Policy notes are incomplete: {target.api_id}")
        if monitoring_eligible_api_ids is not None:
            _require(
                target.api_id in monitoring_eligible_api_ids,
                f"Target is absent or ineligible in the Day 1 registry: {target.api_id}",
            )
        seen_ids.add(target.api_id)
        targets.append(target)

    enabled_count = sum(target.live_monitoring_enabled for target in targets)
    _require(enabled_count > 0, "At least one reviewed target is required")
    _require(
        enabled_count <= policy.max_targets_per_run,
        "Enabled targets exceed the per-run request budget",
    )
    return MonitoringConfiguration(1, policy, tuple(targets))


class UrllibTransport:
    """Small standard-library transport used only for explicitly requested live runs."""

    def request(
        self,
        *,
        url: str,
        method: str,
        timeout_seconds: float,
        headers: Mapping[str, str],
    ) -> TransportResponse:
        request = Request(url, method=method, headers=dict(headers))
        with urlopen(request, timeout=timeout_seconds) as response:
            response.read(1)
            return TransportResponse(response.status, dict(response.headers.items()))


def _content_type(headers: Mapping[str, str]) -> str:
    return next(
        (value for key, value in headers.items() if key.lower() == "content-type"),
        "",
    )


def _classify_exception(error: BaseException) -> tuple[str, str]:
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout", "request exceeded its bounded timeout"
    if isinstance(reason, socket.gaierror):
        return "dns_error", "host name could not be resolved"
    if isinstance(reason, (ssl.SSLCertVerificationError, ssl.SSLError)):
        return "tls_error", "TLS negotiation or certificate validation failed"
    if isinstance(reason, (ConnectionError, OSError)):
        return "connection_error", "connection could not be established or completed"
    return "unexpected_error", "transport raised an unexpected exception"


class HealthCheckEngine:
    """Execute independent low-volume checks without cascading on one failure."""

    def __init__(
        self,
        configuration: MonitoringConfiguration,
        transport: HttpTransport,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.configuration = configuration
        self.transport = transport
        self.monotonic = monotonic

    def _check_target(
        self,
        target: MonitoringTarget,
        *,
        run_id: str,
        observed_at: str,
    ) -> HealthCheckResult:
        started = self.monotonic()
        try:
            response = self.transport.request(
                url=target.endpoint,
                method=target.method,
                timeout_seconds=target.timeout_seconds,
                headers={
                    "Accept": target.expected_content_type,
                    "User-Agent": self.configuration.policy.user_agent,
                },
            )
            status_code = response.status_code
            if status_code not in target.expected_statuses:
                outcome, error_type = "unhealthy", "http_status"
                detail = f"HTTP {status_code} was outside expected statuses {list(target.expected_statuses)}"
            elif not _content_type(response.headers).lower().startswith(
                target.expected_content_type.lower()
            ):
                outcome, error_type = "degraded", "response_contract"
                detail = f"content type did not start with {target.expected_content_type}"
            else:
                outcome, error_type, detail = "healthy", None, None
        except HTTPError as error:
            status_code = error.code
            outcome, error_type = "unhealthy", "http_status"
            detail = f"HTTP {error.code} was outside expected statuses {list(target.expected_statuses)}"
        except Exception as error:  # isolate every target, including adapter defects
            status_code = None
            error_type, detail = _classify_exception(error)
            outcome = "unhealthy"
        elapsed_ms = max(0, round((self.monotonic() - started) * 1000))
        return HealthCheckResult(
            run_id=run_id,
            observed_at=observed_at,
            api_id=target.api_id,
            endpoint=target.endpoint,
            status_code=status_code,
            latency_ms=elapsed_ms,
            outcome=outcome,
            error_type=error_type,
            error_detail=detail,
        )

    def run(self, *, run_id: str, observed_at: str) -> list[HealthCheckResult]:
        """Run each enabled and reviewed target once in configuration order."""

        results = []
        for target in self.configuration.targets:
            if target.live_monitoring_enabled and target.policy_review_status == "reviewed":
                results.append(
                    self._check_target(target, run_id=run_id, observed_at=observed_at)
                )
        return results
