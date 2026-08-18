# Incident operations policy

Day 3 converts the typed Day 2 health-check stream into incidents that can be reproduced, explained, and handed to an owner. The incident engine is deterministic and performs no network requests.

## Incident identity and lifecycle

An incident starts when a configured API first produces an availability, latency, authentication, rate-limit, or response-contract signal. Its ID is a stable SHA-256-derived value over the API ID, failure type, and first-observed timestamp. Rebuilding the same health history therefore produces the same identity without relying on a database sequence.

Lifecycle states are:

| State | Meaning |
|---|---|
| `open` | The last relevant observation still shows the failure. |
| `resolved` | A later observation met availability, contract, and latency rules. |
| `superseded` | A different failure type replaced the signal without evidence of healthy recovery. |

A repeated observation with the same failure type extends the active incident. A healthy observation appends recovery evidence, sets `resolved_at`, and closes it. A later recurrence gets a new identity, preserving intermittent behavior instead of merging unrelated windows.

## Failure signals

Classification uses only recorded health-check fields and configured thresholds:

| Failure type | Deterministic signal |
|---|---|
| `availability` | `unhealthy` outcome, except a more specific authentication or rate-limit status |
| `latency_degradation` | Latency at least 2× baseline and at least 200 ms; 3× baseline is severe |
| `authentication_failure` | HTTP 401 or 403 |
| `rate_limiting` | HTTP 429 |
| `schema_drift` | Day 2 `response_contract` failure |

The per-service baseline is an explicit fixture value in `config/incident_policy.json`; it is not calculated from the small synthetic history or presented as provider performance.

## Severity rules

Each incident records every matched rule ID and a plain-language explanation. Severity represents the highest urgency reached during that incident.

| Rule | Starting severity |
|---|---|
| One availability failure | `SEV-3` |
| Two consecutive availability failures | `SEV-2` |
| Three consecutive availability failures | `SEV-1` |
| Latency at least 2× baseline and 200 ms | `SEV-3` |
| Latency at least 3× baseline | `SEV-2` |
| Authentication or rate-limit status | `SEV-2` |
| Response-contract drift | `SEV-3` |
| Configured `high` criticality | Escalate one level, capped at `SEV-1` |

Availability, duration, latency, explicit HTTP signals, and configured criticality are evidence. Customer counts, revenue loss, SLA breach, and provider-wide outage are not inferred. Criticality values and owners in this portfolio are labeled synthetic assumptions so generated incidents cannot be mistaken for claims about the public providers or their users.

## Evidence and response

Every evidence item retains run ID, timestamp, reviewed endpoint, health outcome, status, latency, error taxonomy, interpreted signal, and sanitized detail. Each incident also retains the affected API name and stable API ID, first/last observed timestamps, peak consecutive failures, ownership, and a failure-specific recommended action.

Recommended actions are intentionally bounded: preserve evidence, verify configuration and provider documentation, reduce request volume for 429 responses, avoid recording credentials, and do not introduce retries during outages without policy review.

## Deterministic scenarios

`data/mock_health_runs.json` labels fixture observations for healthy recovery, intermittent latency degradation, sustained outage, rate limiting, authentication failure, and schema drift. These scenarios are synthetic and exercise the production data contract without touching the network.
