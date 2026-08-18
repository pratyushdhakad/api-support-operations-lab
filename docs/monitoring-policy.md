# Controlled monitoring policy

Day 2 separates discovery from permission. A catalog row can be `monitoring_eligible` because it advertises no authentication and HTTPS, but the engine will not use that row until an operator has reviewed and added an exact endpoint to `config/monitoring_targets.json`.

## Review record

The target allowlist was reviewed on 2026-08-17 against provider documentation:

| Target | Exact request shape | Review basis |
|---|---|---|
| Art Institute of Chicago | One artwork with only `id,title` fields | The provider documents `GET /artworks`, `limit`, and `fields`, and recommends field selection to reduce work. |
| NHTSA vPIC | One exact numeric manufacturer-detail lookup in JSON | The provider documents the endpoint and warns that quotas and rate limits apply. |
| Open-Meteo | One coordinate, one current variable, one forecast day | The provider documents the free non-commercial endpoint and its usage limit. |

Provider documentation remains authoritative. This record is an internal scope review, not a claim that a provider granted special authorization. If terms, robots guidance, authentication, or provider requests change, disable the target before another live run.

## Enforced request controls

- HTTPS `GET` only; endpoints cannot contain credentials or fragments.
- Three targets maximum per run and one request per target.
- At least 60 minutes between live runs sharing the same runtime history; the CLI refuses earlier repeats.
- Per-target timeouts of three or four seconds, with a five-second policy ceiling.
- A project-and-contact-identifying user agent on every request.
- A minimal expected JSON response contract; bodies are not retained.
- Live traffic requires `--live`; tests and normal artifact generation inject deterministic fixtures.

The CLI deliberately does not implement automatic retries. A retry could amplify provider load during an outage and distort latency history. Scheduling and stop controls belong to an operator-owned job in a later project phase. The CLI enforces the minimum interval from live results in its selected output directory, so operators must not rotate that directory to evade the guardrail.

## Outcomes and error taxonomy

| Outcome | Error type | Interpretation |
|---|---|---|
| `healthy` | null | Expected status and JSON content type |
| `degraded` | `response_contract` | HTTP succeeded but the response no longer matched the expected content type |
| `unhealthy` | `http_status` | Provider returned an unexpected HTTP status |
| `unhealthy` | `timeout` | Request exceeded its bounded timeout |
| `unhealthy` | `dns_error` | Host name resolution failed |
| `unhealthy` | `tls_error` | Certificate validation or TLS negotiation failed |
| `unhealthy` | `connection_error` | A connection could not be established or completed |
| `unhealthy` | `unexpected_error` | The transport raised an uncategorized exception |

Each target is isolated. A failure is converted to a result and the run continues, preserving visibility across the rest of the allowlist.

## Artifact interpretation

`data/mock_health_runs.json` intentionally covers success, response-contract drift, intermittent latency, rate limiting, authentication signals, sustained timeout, and recovery. It is synthetic test data, not measured service performance. Live results write to an operator-selected directory and are not mixed into the tracked portfolio artifacts.
