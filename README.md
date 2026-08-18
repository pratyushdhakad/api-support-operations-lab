# API Support Operations Lab

An AI-automation portfolio project that turns a public API catalog into a monitored service registry, operational incidents, and a decision-ready support dashboard.

> The project uses public metadata from the community-maintained [public-apis catalog](https://github.com/public-apis/public-apis). Committed catalog and health-check fixtures demonstrate the engineering workflow; they are not live availability claims.

## Business question

Which external APIs are suitable for monitored workflows, and how should an operations team detect, classify, prioritize, and explain service failures?

The eventual decision owner is an automation or data-platform lead responsible for choosing dependencies and responding when an upstream service becomes unreliable.

## Day 3 build status

The repository currently:

- parses Markdown API tables into typed records;
- normalizes authentication, HTTPS, and CORS metadata;
- assigns stable category-and-name registry identifiers;
- identifies no-auth HTTPS services eligible for controlled monitoring;
- requires a separate, reviewed allowlist with exact endpoints and policy notes;
- runs bounded, low-volume checks with a descriptive user agent;
- captures status, latency, outcome, and a stable failure taxonomy;
- preserves latency history across deterministic mock runs;
- converts health observations into stable, auditable incident lifecycles;
- applies explainable severity rules for availability, consecutive failures, latency, authentication, rate limits, response contracts, and configured criticality;
- records evidence, ownership, recovery, and bounded recommended actions; and
- tests parsing, policy enforcement, failure isolation, incident scenarios, and byte-for-byte reproducibility.

Tests, `make run`, and committed artifacts never call external endpoints. The live mode is opt-in and makes at most one request to each of three reviewed targets.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make test
make run
```

Generated outputs are written to `artifacts/`:

- `api_registry.csv` — analyst-friendly service registry;
- `api_registry.json` — typed machine-readable registry; and
- `registry_summary.json` — category, authentication, and monitoring-readiness metrics;
- `health_check_history.csv` — analyst-friendly status and latency observations;
- `health_check_results.json` — complete typed health-check results;
- `latency_history.json` — per-target latency and outcome history; and
- `monitoring_summary.json` — operational outcome and error counts;
- `incident_timeline.csv` — analyst-friendly incident lifecycle and triage fields;
- `incidents.json` — complete incident identity, evidence, severity, ownership, and action records; and
- `incident_summary.json` — lifecycle, failure-type, and peak-severity counts.

Run the complete deterministic pipeline with:

```bash
make pipeline
```

An operator may deliberately perform one live run. By default, results go to the
ignored `runtime/` directory:

```bash
PYTHONPATH=src python3 -m api_support_operations.monitoring_pipeline \
  --live
```

Live mode is not a scheduler. It uses prior results in the selected output directory to enforce the documented one-hour minimum interval. Operators must reuse that directory and reassess provider policy before changing scope.

## Decision flow

```mermaid
flowchart LR
    A[Public catalog fixture] --> B[Markdown parser]
    B --> C[Normalized API records]
    C --> D[Deterministic service registry]
    D --> E[Monitoring eligibility]
    E --> F[Reviewed exact-endpoint allowlist]
    F --> G[Bounded health-check engine]
    G --> H[Latency history and failure taxonomy]
    H --> I[Deterministic incident engine]
    I --> J[Auditable severity and recovery timeline]
```

## Five-day roadmap

1. **Catalog foundation:** parser, registry, deterministic fixtures, tests
2. **Health monitoring:** latency history, failure handling, controlled endpoint probes — complete
3. **Incident operations:** incident model, severity rules, automated tests — complete
4. **AI evaluation:** failure classification, evaluation harness, cost tracking
5. **Decision experience:** executive dashboard, CI, GitHub Pages deployment

## Repository map

```text
src/api_support_operations/  catalog, monitoring, incident engines, and artifact pipelines
config/                      reviewed monitoring allowlist and explicit incident policy
data/                        attributed catalog and deterministic operational fixtures
tests/                       policy, resilience, incident, parser, and reproducibility tests
artifacts/                   generated registry, monitoring, and incident outputs
docs/                        data contracts and operating assumptions
```

## Responsible-use guardrails

- The catalog is a discovery source, not proof that an API is currently available.
- Provider documentation remains authoritative for authentication, usage, and rate limits.
- Monitoring uses a three-target allowlist, descriptive user agent, bounded timeouts, and a one-hour minimum interval.
- Catalog presence and computed eligibility are discovery signals, never authorization to make a request.
- Tests and portfolio artifacts use deterministic transport fixtures and cannot touch the network.
- Business criticality, latency baselines, and ownership are labeled synthetic portfolio assumptions, not observed customer impact.
- No employer, customer, credential, or private operational data belongs in this repository.

## Current limitations

- The Markdown parser supports the table structure used by the catalog fixture; unusual embedded pipe characters require escaping.
- Monitoring eligibility still means no authentication plus HTTPS support; live access additionally requires explicit policy review in `config/monitoring_targets.json`.
- The engine records point-in-time reachability and contract health, not provider uptime or SLA compliance.
- The fixture history is synthetic and must not be presented as observed provider performance.
- Severity is a deterministic triage priority for this exercise, not a claim about customer, revenue, or provider-wide impact.
- CORS is retained as metadata but does not determine server-side monitoring eligibility.

## License

MIT. The source catalog has its own [MIT license](https://github.com/public-apis/public-apis/blob/master/LICENSE).
