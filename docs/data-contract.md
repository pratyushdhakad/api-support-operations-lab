# API registry data contract

Each parsed catalog row becomes one registry record.

| Field | Type | Meaning |
|---|---|---|
| `api_id` | string | Stable slug built from category and API name |
| `category` | string | Catalog section heading |
| `name` | string | Human-readable API name |
| `description` | string | Short catalog description |
| `documentation_url` | string | Provider or API documentation URL |
| `auth_type` | enum-like string | Normalized `none`, `api_key`, `oauth`, `user_agent`, or another slug |
| `https_supported` | boolean/null | Normalized HTTPS support |
| `cors_status` | string | Normalized `yes`, `no`, or `unknown` |
| `monitoring_eligible` | boolean | True when the catalog says no authentication and HTTPS support |
| `source_line` | integer | One-based fixture line for traceability |

## Determinism guarantees

- Records are sorted by category, API name, and identifier.
- Duplicate category/name pairs receive stable numeric suffixes in source order.
- JSON keys, CSV columns, newline behavior, and summary ordering are fixed.
- The pipeline does not include execution timestamps in generated artifacts.

## Day 2 extension

The registry now has a separate reviewed monitoring-target layer containing the exact endpoint, method, timeout, expected response contract, review date, and request-policy notes. Catalog metadata alone never authorizes a live request.

Each health-check result contains:

| Field | Type | Meaning |
|---|---|---|
| `run_id` | string | Stable fixture ID or timestamped live-run ID |
| `observed_at` | ISO 8601 string | When the observation was made |
| `api_id` | string | Foreign key to the Day 1 registry |
| `endpoint` | HTTPS URL | Exact reviewed URL that was checked |
| `status_code` | integer/null | HTTP response status, or null before an HTTP response |
| `latency_ms` | integer | End-to-end elapsed time, including failed requests |
| `outcome` | enum | `healthy`, `degraded`, or `unhealthy` |
| `error_type` | enum/null | Stable operational failure category |
| `error_detail` | string/null | Sanitized explanation without raw response data |

The monitoring fixture and generated artifact timestamps are fixed inputs. The pipeline does not insert an execution timestamp, so committed outputs remain byte-for-byte reproducible.

## Day 3 extension

The incident engine consumes Day 2 `HealthCheckResult` records without changing their schema. Every incident contains:

| Field | Type | Meaning |
|---|---|---|
| `incident_id` | string | Stable hash-derived identity from API, failure type, and first observation |
| `lifecycle_state` | enum | `open`, `resolved`, or `superseded` |
| `first_observed_at` / `last_observed_at` | ISO 8601 string | Auditable incident window |
| `resolved_at` | ISO 8601 string/null | Healthy recovery timestamp, when observed |
| `failure_type` | enum | Availability, latency, authentication, rate limiting, or schema drift |
| `api_id` / `affected_api` | string | Registry foreign key and human-readable service name |
| `evidence` | array | Ordered health observations with endpoint and interpreted signal |
| `severity` | enum | Peak deterministic priority: `SEV-1`, `SEV-2`, or `SEV-3` |
| `severity_rule_ids` | string array | Every severity rule matched during the lifecycle |
| `severity_explanation` | string | Human-readable explanation of peak severity |
| `business_criticality` / `criticality_basis` | string | Explicit synthetic assumption and its disclaimer |
| `owner` | string | Configured team accountable for triage |
| `recommended_action` | string | Failure-specific bounded next action |
| `consecutive_failure_count` | integer | Maximum uninterrupted observations for the failure type |

Incident ordering, evidence ordering, IDs, JSON keys, CSV columns, and summaries are deterministic. Healthy observations are retained only when they close an active incident; this keeps recovery auditable without creating healthy incidents.

## Day 4 extension

Day 4 consumes, but does not alter, the Day 3 incident schema. Each separate classification record contains:

| Field | Type | Meaning |
|---|---|---|
| `incident_id` | string | Foreign key to the Day 3 incident |
| `failure_category` | enum | Five operational categories or `unknown` |
| `priority` | enum | `SEV-1`, `SEV-2`, `SEV-3`, or `UNASSESSED` |
| `summary` | string | Concise proposed handoff summary |
| `recommended_owner` | string | Reviewed owner or `Human triage` |
| `confidence` | number | Candidate confidence from 0 to 1 |
| `review_state` | enum | `auto_classified` or `human_review_required` |
| `abstention_reason` | string/null | Transparent review triggers |
| `prompt_metadata` | object | Provider/model and version/hash provenance, with external-call flag |
| `modeled_usage` | object | Deterministic token estimate and explicitly modeled USD cost |

Evaluation fixtures are labeled synthetic inputs. The report fixes class order, threshold order, JSON ordering, rounding, and cost precision. Wall-clock latency is committed only as a coarse bucket, avoiding unstable raw timing values while preserving the measurement basis.
