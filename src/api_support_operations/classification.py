"""Provider-agnostic incident classification with a deterministic baseline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Protocol


FAILURE_CATEGORIES = (
    "authentication_failure",
    "availability",
    "latency_degradation",
    "rate_limiting",
    "schema_drift",
    "unknown",
)
PRIORITIES = ("SEV-1", "SEV-2", "SEV-3", "UNASSESSED")
REVIEW_STATES = ("auto_classified", "human_review_required")
PROMPT_TEMPLATE = """Classify the incident evidence into the allowed failure category and priority.
Return a concise summary, recommended owner, confidence, and whether human review is required.
Never infer customer impact, credentials, or facts absent from the supplied incident record."""


class ClassificationConfigurationError(ValueError):
    """Raised when classification policy is incomplete or misleading."""


@dataclass(frozen=True)
class PricingModel:
    name: str
    input_usd_per_million_tokens: Decimal
    output_usd_per_million_tokens: Decimal
    currency: str
    basis: str


@dataclass(frozen=True)
class ClassificationConfiguration:
    schema_version: int
    operating_confidence_threshold: float
    prompt_version: str
    classifier_version: str
    prompt_tokens: int
    allowed_owners: tuple[str, ...]
    pricing: PricingModel


@dataclass(frozen=True)
class ClassificationInput:
    incident_id: str
    affected_api: str
    detector_signal: str | None
    outcome: str
    status_code: int | None
    error_type: str | None
    latency_ratio: float | None
    priority_hint: str
    owner_hint: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PromptMetadata:
    provider: str
    model: str
    classifier_version: str
    prompt_version: str
    prompt_template_sha256: str
    external_api_called: bool


@dataclass(frozen=True)
class ModeledUsage:
    input_tokens: int
    output_tokens: int
    input_cost_usd: str
    output_cost_usd: str
    total_cost_usd: str
    currency: str
    basis: str


@dataclass(frozen=True)
class IncidentClassification:
    incident_id: str
    failure_category: str
    priority: str
    summary: str
    recommended_owner: str
    confidence: float
    review_state: str
    abstention_reason: str | None
    prompt_metadata: PromptMetadata
    modeled_usage: ModeledUsage

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class IncidentClassifier(Protocol):
    """Interface implemented by deterministic or external model providers."""

    def classify(self, incident: ClassificationInput) -> IncidentClassification:
        """Classify one sanitized incident record."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ClassificationConfigurationError(message)


def load_classification_configuration(path: Path) -> ClassificationConfiguration:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(payload.get("schema_version") == 1, "Unsupported classification schema")
    threshold = float(payload.get("operating_confidence_threshold", -1))
    _require(0 < threshold <= 1, "Operating confidence threshold must be in (0, 1]")
    pricing = payload.get("modeled_pricing", {})
    basis = str(pricing.get("basis", ""))
    _require("Modeled only" in basis, "Pricing must be explicitly labeled modeled only")
    pricing_model = PricingModel(
        name=str(pricing.get("name", "")),
        input_usd_per_million_tokens=Decimal(
            str(pricing.get("input_usd_per_million_tokens", "-1"))
        ),
        output_usd_per_million_tokens=Decimal(
            str(pricing.get("output_usd_per_million_tokens", "-1"))
        ),
        currency=str(pricing.get("currency", "")),
        basis=basis,
    )
    _require(bool(pricing_model.name), "Modeled pricing name is required")
    _require(pricing_model.currency == "USD", "Modeled pricing currency must be USD")
    _require(
        pricing_model.input_usd_per_million_tokens >= 0
        and pricing_model.output_usd_per_million_tokens >= 0,
        "Modeled token prices cannot be negative",
    )
    owners = tuple(str(value) for value in payload.get("allowed_owners", []))
    _require(bool(owners) and all(owners), "At least one allowed owner is required")
    prompt_version = str(payload.get("prompt_version", ""))
    classifier_version = str(payload.get("classifier_version", ""))
    prompt_tokens = int(payload.get("modeled_prompt_tokens", 0))
    _require(bool(prompt_version), "Prompt version is required")
    _require(bool(classifier_version), "Classifier version is required")
    _require(prompt_tokens > 0, "Modeled prompt tokens must be positive")
    return ClassificationConfiguration(
        schema_version=1,
        operating_confidence_threshold=threshold,
        prompt_version=prompt_version,
        classifier_version=classifier_version,
        prompt_tokens=prompt_tokens,
        allowed_owners=owners,
        pricing=pricing_model,
    )


def classification_input_from_incident(payload: Mapping[str, object]) -> ClassificationInput:
    """Create a sanitized classifier input without changing the Day 3 contract."""

    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("Incident must contain at least one evidence item")
    first_failure = next(
        (
            item
            for item in evidence
            if isinstance(item, dict) and item.get("signal") != "healthy_recovery"
        ),
        None,
    )
    if first_failure is None:
        raise ValueError("Incident evidence must contain a failure signal")
    detail = str(first_failure.get("detail", ""))
    latency_ratio: float | None = None
    if first_failure.get("signal") == "latency_degradation":
        marker = "latency was "
        suffix = "x the configured baseline"
        if marker in detail and suffix in detail:
            value = detail.split(marker, 1)[1].split(suffix, 1)[0].strip()
            try:
                latency_ratio = float(value)
            except ValueError:
                latency_ratio = None
    return ClassificationInput(
        incident_id=str(payload.get("incident_id", "")),
        affected_api=str(payload.get("affected_api", "")),
        detector_signal=(
            str(first_failure.get("signal")) if first_failure.get("signal") is not None else None
        ),
        outcome=str(first_failure.get("outcome", "")),
        status_code=(
            int(first_failure["status_code"])
            if first_failure.get("status_code") is not None
            else None
        ),
        error_type=(
            str(first_failure.get("error_type"))
            if first_failure.get("error_type") is not None
            else None
        ),
        latency_ratio=latency_ratio,
        priority_hint=str(payload.get("severity", "UNASSESSED")),
        owner_hint=(str(payload.get("owner")) if payload.get("owner") is not None else None),
    )


class DeterministicIncidentClassifier:
    """Offline reference implementation used for reproducible evaluation."""

    def __init__(self, configuration: ClassificationConfiguration) -> None:
        self.configuration = configuration
        prompt_hash = hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest()
        self.metadata = PromptMetadata(
            provider="deterministic-baseline",
            model="structured-rules",
            classifier_version=configuration.classifier_version,
            prompt_version=configuration.prompt_version,
            prompt_template_sha256=prompt_hash,
            external_api_called=False,
        )

    def _candidate(self, incident: ClassificationInput) -> tuple[str, float]:
        if incident.status_code in (401, 403):
            return "authentication_failure", 0.99
        if incident.status_code == 429:
            return "rate_limiting", 0.99
        if incident.error_type == "response_contract":
            return "schema_drift", 0.98
        if incident.latency_ratio is not None and incident.latency_ratio >= 2:
            return "latency_degradation", 0.91
        if incident.detector_signal in FAILURE_CATEGORIES[:-1]:
            confidence = {
                "authentication_failure": 0.97,
                "availability": 0.95,
                "latency_degradation": 0.90,
                "rate_limiting": 0.97,
                "schema_drift": 0.96,
            }[incident.detector_signal]
            return incident.detector_signal, confidence
        if incident.outcome == "unhealthy":
            return "availability", 0.72
        return "unknown", 0.20

    def _usage(self, input_payload: str, output_payload: str) -> ModeledUsage:
        input_tokens = self.configuration.prompt_tokens + math.ceil(len(input_payload) / 4)
        output_tokens = math.ceil(len(output_payload) / 4)
        million = Decimal("1000000")
        input_cost = (
            Decimal(input_tokens)
            * self.configuration.pricing.input_usd_per_million_tokens
            / million
        )
        output_cost = (
            Decimal(output_tokens)
            * self.configuration.pricing.output_usd_per_million_tokens
            / million
        )
        quantum = Decimal("0.00000001")
        money = lambda value: str(value.quantize(quantum, rounding=ROUND_HALF_UP))
        return ModeledUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost_usd=money(input_cost),
            output_cost_usd=money(output_cost),
            total_cost_usd=money(input_cost + output_cost),
            currency=self.configuration.pricing.currency,
            basis=self.configuration.pricing.basis,
        )

    def classify(self, incident: ClassificationInput) -> IncidentClassification:
        category, confidence = self._candidate(incident)
        priority = incident.priority_hint if incident.priority_hint in PRIORITIES[:-1] else "UNASSESSED"
        owner = (
            incident.owner_hint
            if incident.owner_hint in self.configuration.allowed_owners
            else "Human triage"
        )
        reasons: list[str] = []
        if category == "unknown":
            reasons.append("no supported failure signal")
        if priority == "UNASSESSED":
            reasons.append("priority was not supplied by the incident policy")
        if owner == "Human triage":
            reasons.append("owner is missing or outside the reviewed routing policy")
        if confidence < self.configuration.operating_confidence_threshold:
            reasons.append(
                f"confidence {confidence:.2f} is below the {self.configuration.operating_confidence_threshold:.2f} threshold"
            )
        review_state = "human_review_required" if reasons else "auto_classified"
        phrase = {
            "authentication_failure": "authentication failed",
            "availability": "availability failed",
            "latency_degradation": "latency exceeded the reviewed baseline",
            "rate_limiting": "request rate was limited",
            "schema_drift": "the reviewed response contract changed",
            "unknown": "failure signal needs human classification",
        }[category]
        summary = f"{incident.affected_api}: {phrase} ({priority})."
        input_payload = json.dumps(incident.to_dict(), sort_keys=True, separators=(",", ":"))
        output_payload = json.dumps(
            {
                "failure_category": category,
                "priority": priority,
                "recommended_owner": owner,
                "review_state": review_state,
                "summary": summary,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return IncidentClassification(
            incident_id=incident.incident_id,
            failure_category=category,
            priority=priority,
            summary=summary,
            recommended_owner=owner,
            confidence=confidence,
            review_state=review_state,
            abstention_reason="; ".join(reasons) if reasons else None,
            prompt_metadata=self.metadata,
            modeled_usage=self._usage(input_payload, output_payload),
        )
