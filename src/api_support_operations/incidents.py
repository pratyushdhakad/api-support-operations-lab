"""Auditable incident lifecycle and deterministic severity rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Iterable

from .monitoring import HealthCheckResult


SEVERITY_ORDER = {"SEV-1": 1, "SEV-2": 2, "SEV-3": 3}
CRITICALITY_LEVELS = ("low", "medium", "high")


class IncidentConfigurationError(ValueError):
    """Raised when incident policy cannot produce trustworthy classifications."""


@dataclass(frozen=True)
class SeverityPolicy:
    availability_sev2_consecutive_failures: int
    availability_sev1_consecutive_failures: int
    latency_degradation_multiplier: float
    severe_latency_multiplier: float
    minimum_latency_degradation_ms: int
    authentication_statuses: tuple[int, ...]
    rate_limit_statuses: tuple[int, ...]
    high_criticality_escalates_one_level: bool


@dataclass(frozen=True)
class ServiceIncidentPolicy:
    api_id: str
    name: str
    owner: str
    business_criticality: str
    criticality_basis: str
    baseline_latency_ms: int


@dataclass(frozen=True)
class IncidentConfiguration:
    schema_version: int
    policy: SeverityPolicy
    services: tuple[ServiceIncidentPolicy, ...]


@dataclass(frozen=True)
class IncidentEvidence:
    run_id: str
    observed_at: str
    endpoint: str
    outcome: str
    status_code: int | None
    latency_ms: int
    error_type: str | None
    signal: str
    detail: str


@dataclass
class Incident:
    incident_id: str
    lifecycle_state: str
    first_observed_at: str
    last_observed_at: str
    resolved_at: str | None
    failure_type: str
    api_id: str
    affected_api: str
    evidence: list[IncidentEvidence]
    severity: str
    severity_rule_ids: list[str]
    severity_explanation: str
    business_criticality: str
    criticality_basis: str
    owner: str
    recommended_action: str
    consecutive_failure_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IncidentConfigurationError(message)


def load_incident_configuration(
    path: Path,
    *,
    monitored_api_ids: set[str] | None = None,
) -> IncidentConfiguration:
    """Load ownership, synthetic criticality, baselines, and severity thresholds."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(payload.get("schema_version") == 1, "Unsupported incident schema")
    raw = payload.get("policy", {})
    policy = SeverityPolicy(
        availability_sev2_consecutive_failures=int(
            raw.get("availability_sev2_consecutive_failures", 0)
        ),
        availability_sev1_consecutive_failures=int(
            raw.get("availability_sev1_consecutive_failures", 0)
        ),
        latency_degradation_multiplier=float(raw.get("latency_degradation_multiplier", 0)),
        severe_latency_multiplier=float(raw.get("severe_latency_multiplier", 0)),
        minimum_latency_degradation_ms=int(raw.get("minimum_latency_degradation_ms", 0)),
        authentication_statuses=tuple(int(value) for value in raw.get("authentication_statuses", [])),
        rate_limit_statuses=tuple(int(value) for value in raw.get("rate_limit_statuses", [])),
        high_criticality_escalates_one_level=bool(
            raw.get("high_criticality_escalates_one_level", False)
        ),
    )
    _require(
        1 <= policy.availability_sev2_consecutive_failures
        < policy.availability_sev1_consecutive_failures,
        "Availability thresholds must increase from SEV-2 to SEV-1",
    )
    _require(
        1 < policy.latency_degradation_multiplier < policy.severe_latency_multiplier,
        "Latency multipliers must increase from degraded to severe",
    )
    _require(policy.minimum_latency_degradation_ms > 0, "Minimum latency must be positive")
    _require(bool(policy.authentication_statuses), "Authentication statuses are required")
    _require(bool(policy.rate_limit_statuses), "Rate-limit statuses are required")
    _require(
        not set(policy.authentication_statuses) & set(policy.rate_limit_statuses),
        "Authentication and rate-limit statuses must not overlap",
    )

    services: list[ServiceIncidentPolicy] = []
    seen: set[str] = set()
    for raw_service in payload.get("services", []):
        service = ServiceIncidentPolicy(
            api_id=str(raw_service.get("api_id", "")),
            name=str(raw_service.get("name", "")),
            owner=str(raw_service.get("owner", "")),
            business_criticality=str(raw_service.get("business_criticality", "")),
            criticality_basis=str(raw_service.get("criticality_basis", "")),
            baseline_latency_ms=int(raw_service.get("baseline_latency_ms", 0)),
        )
        _require(bool(service.api_id), "Service API ID is required")
        _require(service.api_id not in seen, f"Duplicate incident service: {service.api_id}")
        _require(bool(service.name), f"Service name is required: {service.api_id}")
        _require(bool(service.owner), f"Owner is required: {service.api_id}")
        _require(
            service.business_criticality in CRITICALITY_LEVELS,
            f"Unsupported business criticality: {service.api_id}",
        )
        _require(
            "Synthetic portfolio assumption" in service.criticality_basis,
            f"Criticality must be explicitly identified as synthetic: {service.api_id}",
        )
        _require(service.baseline_latency_ms > 0, f"Latency baseline is required: {service.api_id}")
        if monitored_api_ids is not None:
            _require(
                service.api_id in monitored_api_ids,
                f"Incident service is not in the monitoring allowlist: {service.api_id}",
            )
        seen.add(service.api_id)
        services.append(service)
    _require(bool(services), "At least one incident service is required")
    if monitored_api_ids is not None:
        _require(seen == monitored_api_ids, "Incident policy must cover every monitored API")
    return IncidentConfiguration(1, policy, tuple(services))


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Invalid observation timestamp: {value}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"Observation timestamp must include a timezone: {value}")
    return parsed


def _incident_id(api_id: str, failure_type: str, first_observed_at: str) -> str:
    identity = f"{api_id}|{failure_type}|{first_observed_at}".encode("utf-8")
    return f"inc-{hashlib.sha256(identity).hexdigest()[:12]}"


def _signal_for(
    result: HealthCheckResult,
    service: ServiceIncidentPolicy,
    policy: SeverityPolicy,
) -> tuple[str | None, str]:
    if result.status_code in policy.authentication_statuses:
        return "authentication_failure", f"HTTP {result.status_code} is an authentication signal"
    if result.status_code in policy.rate_limit_statuses:
        return "rate_limiting", f"HTTP {result.status_code} is a rate-limit signal"
    if result.error_type == "response_contract":
        return "schema_drift", "response contract no longer matched the reviewed content type"
    if result.outcome == "unhealthy":
        detail = result.error_type or "unclassified health-check failure"
        return "availability", f"health check was unavailable: {detail}"
    latency_threshold = max(
        policy.minimum_latency_degradation_ms,
        round(service.baseline_latency_ms * policy.latency_degradation_multiplier),
    )
    if result.latency_ms >= latency_threshold:
        ratio = result.latency_ms / service.baseline_latency_ms
        return "latency_degradation", f"latency was {ratio:.2f}x the configured baseline"
    if result.outcome == "degraded":
        return "availability", "health check reported an uncategorized degraded outcome"
    return None, "healthy observation met availability, contract, and latency rules"


def _recommended_action(failure_type: str) -> str:
    return {
        "availability": (
            "Verify provider status and local connectivity, preserve evidence, and escalate to the owner "
            "if failures persist; do not add automatic retries during an outage."
        ),
        "rate_limiting": (
            "Pause nonessential requests, review documented limits and request cadence, and add bounded "
            "backoff only after policy review."
        ),
        "authentication_failure": (
            "Validate credential and authorization configuration without recording secrets, then review "
            "provider authentication documentation before retrying."
        ),
        "schema_drift": (
            "Compare the observed contract signal with provider documentation and update the adapter only "
            "after confirming the intended response shape."
        ),
        "latency_degradation": (
            "Review the latency trend and dependency path, continue bounded monitoring, and avoid claiming "
            "an SLA breach from synthetic observations."
        ),
    }[failure_type]


def _severity_for(
    failure_type: str,
    consecutive_failures: int,
    latency_ms: int,
    service: ServiceIncidentPolicy,
    policy: SeverityPolicy,
) -> tuple[str, tuple[str, ...], str]:
    if failure_type == "availability":
        if consecutive_failures >= policy.availability_sev1_consecutive_failures:
            level, rule = 1, "AVAILABILITY_SUSTAINED_SEV1"
            reason = f"availability failed for {consecutive_failures} consecutive observations"
        elif consecutive_failures >= policy.availability_sev2_consecutive_failures:
            level, rule = 2, "AVAILABILITY_REPEATED_SEV2"
            reason = f"availability failed for {consecutive_failures} consecutive observations"
        else:
            level, rule = 3, "AVAILABILITY_SINGLE_SEV3"
            reason = "availability failed for one observation"
    elif failure_type == "latency_degradation":
        ratio = latency_ms / service.baseline_latency_ms
        if ratio >= policy.severe_latency_multiplier:
            level, rule = 2, "LATENCY_SEVERE_SEV2"
        else:
            level, rule = 3, "LATENCY_DEGRADED_SEV3"
        reason = f"latency was {ratio:.2f}x the configured baseline"
    elif failure_type == "authentication_failure":
        level, rule, reason = 2, "AUTHENTICATION_SIGNAL_SEV2", "HTTP status indicated authentication failure"
    elif failure_type == "rate_limiting":
        level, rule, reason = 2, "RATE_LIMIT_SIGNAL_SEV2", "HTTP status indicated rate limiting"
    else:
        level, rule, reason = 3, "SCHEMA_DRIFT_SEV3", "the reviewed response contract changed"

    rules = [rule]
    if policy.high_criticality_escalates_one_level and service.business_criticality == "high":
        escalated = max(1, level - 1)
        if escalated != level:
            level = escalated
            rules.append("HIGH_CRITICALITY_ESCALATION")
            reason += "; configured synthetic criticality escalated one level"
    severity = f"SEV-{level}"
    return severity, tuple(rules), f"{severity}: {reason}."


def _evidence(result: HealthCheckResult, signal: str, detail: str) -> IncidentEvidence:
    return IncidentEvidence(
        run_id=result.run_id,
        observed_at=result.observed_at,
        endpoint=result.endpoint,
        outcome=result.outcome,
        status_code=result.status_code,
        latency_ms=result.latency_ms,
        error_type=result.error_type,
        signal=signal,
        detail=detail,
    )


def build_incidents(
    results: Iterable[HealthCheckResult],
    configuration: IncidentConfiguration,
) -> list[Incident]:
    """Convert ordered health observations into auditable incident lifecycles."""

    service_by_id = {service.api_id: service for service in configuration.services}
    ordered = sorted(results, key=lambda result: (_parse_timestamp(result.observed_at), result.api_id, result.run_id))
    active: dict[str, Incident] = {}
    incidents: list[Incident] = []

    for result in ordered:
        if result.api_id not in service_by_id:
            raise ValueError(f"Health result has no incident policy: {result.api_id}")
        service = service_by_id[result.api_id]
        signal, detail = _signal_for(result, service, configuration.policy)
        current = active.get(result.api_id)

        if signal is None:
            if current is not None:
                current.evidence.append(_evidence(result, "healthy_recovery", detail))
                current.last_observed_at = result.observed_at
                current.resolved_at = result.observed_at
                current.lifecycle_state = "resolved"
                active.pop(result.api_id)
            continue

        if current is not None and current.failure_type != signal:
            current.lifecycle_state = "superseded"
            active.pop(result.api_id)
            current = None

        if current is None:
            severity, rules, explanation = _severity_for(
                signal, 1, result.latency_ms, service, configuration.policy
            )
            current = Incident(
                incident_id=_incident_id(result.api_id, signal, result.observed_at),
                lifecycle_state="open",
                first_observed_at=result.observed_at,
                last_observed_at=result.observed_at,
                resolved_at=None,
                failure_type=signal,
                api_id=result.api_id,
                affected_api=service.name,
                evidence=[_evidence(result, signal, detail)],
                severity=severity,
                severity_rule_ids=list(rules),
                severity_explanation=explanation,
                business_criticality=service.business_criticality,
                criticality_basis=service.criticality_basis,
                owner=service.owner,
                recommended_action=_recommended_action(signal),
                consecutive_failure_count=1,
            )
            incidents.append(current)
            active[result.api_id] = current
            continue

        current.evidence.append(_evidence(result, signal, detail))
        current.last_observed_at = result.observed_at
        current.consecutive_failure_count += 1
        severity, rules, explanation = _severity_for(
            signal,
            current.consecutive_failure_count,
            result.latency_ms,
            service,
            configuration.policy,
        )
        for rule in rules:
            if rule not in current.severity_rule_ids:
                current.severity_rule_ids.append(rule)
        if SEVERITY_ORDER[severity] < SEVERITY_ORDER[current.severity]:
            current.severity = severity
            current.severity_explanation = explanation

    return sorted(incidents, key=lambda incident: (incident.first_observed_at, incident.api_id, incident.incident_id))
