# API Support Operations Lab

An AI-automation portfolio project that turns a public API catalog into a monitored service registry, operational incidents, and a decision-ready support dashboard.

> The project uses public metadata from the community-maintained [public-apis catalog](https://github.com/public-apis/public-apis). Committed catalog and health-check fixtures demonstrate the engineering workflow; they are not live availability claims.

## Business question

Which external APIs are suitable for monitored workflows, and how should an operations team detect, classify, prioritize, and explain service failures?

The eventual decision owner is an automation or data-platform lead responsible for choosing dependencies and responding when an upstream service becomes unreliable.

## Day 4 build status

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
- records evidence, ownership, recovery, and bounded recommended actions;
- exposes a provider-agnostic incident classifier with an offline deterministic baseline;
- classifies failure category, priority, summary, owner, confidence, and review state;
- evaluates accuracy, macro F1, per-class behavior, threshold coverage, abstention, and latency;
- records prompt/version provenance and explicitly modeled token/cost usage; and
- tests parsing, policy enforcement, failure isolation, incident scenarios, AI review behavior, and byte-for-byte reproducibility.

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
- `incident_summary.json` — lifecycle, failure-type, and peak-severity counts;
- `incident_classifications.json` — Day 4 classifications, review states, metadata, and per-record modeled usage;
- `classification_evaluation.json` — labeled-fixture metrics, threshold analysis, per-class performance, and latency buckets; and
- `classification_cost_summary.json` — illustrative modeled pricing and aggregate usage, never realized spend or savings.

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
    J --> K[Provider-agnostic classifier]
    K --> L[Evaluation, abstention, and modeled cost evidence]
```

## Five-day roadmap

1. **Catalog foundation:** parser, registry, deterministic fixtures, tests
2. **Health monitoring:** latency history, failure handling, controlled endpoint probes — complete
3. **Incident operations:** incident model, severity rules, automated tests — complete
4. **AI evaluation:** failure classification, evaluation harness, cost tracking — complete
5. **Decision experience:** executive dashboard, CI, GitHub Pages deployment

## Repository map

```text
src/api_support_operations/  catalog, monitoring, incident, classification, evaluation, and artifact pipelines
config/                      reviewed monitoring, incident, confidence, ownership, and modeled-pricing policies
data/                        attributed catalog plus deterministic operational and labeled evaluation fixtures
tests/                       policy, resilience, incident, classifier, metric, parser, and reproducibility tests
artifacts/                   generated registry, monitoring, incident, classification, and evaluation outputs
docs/                        data contracts, operating assumptions, review policy, and failure modes
```

## Responsible-use guardrails

- The catalog is a discovery source, not proof that an API is currently available.
- Provider documentation remains authoritative for authentication, usage, and rate limits.
- Monitoring uses a three-target allowlist, descriptive user agent, bounded timeouts, and a one-hour minimum interval.
- Catalog presence and computed eligibility are discovery signals, never authorization to make a request.
- Tests and portfolio artifacts use deterministic transport fixtures and cannot touch the network.
- Business criticality, latency baselines, and ownership are labeled synthetic portfolio assumptions, not observed customer impact.
- Day 4 evaluation labels are synthetic; the baseline needs no secret, paid API, or network access.
- Token and cost values are deterministic models under illustrative rates, not invoices or realized savings.
- No employer, customer, credential, or private operational data belongs in this repository.

## Current limitations

- The Markdown parser supports the table structure used by the catalog fixture; unusual embedded pipe characters require escaping.
- Monitoring eligibility still means no authentication plus HTTPS support; live access additionally requires explicit policy review in `config/monitoring_targets.json`.
- The engine records point-in-time reachability and contract health, not provider uptime or SLA compliance.
- The fixture history is synthetic and must not be presented as observed provider performance.
- Severity is a deterministic triage priority for this exercise, not a claim about customer, revenue, or provider-wide impact.
- The Day 4 rules baseline evaluates the interface, structured signal handling, routing, and abstention policy; it is not evidence of general language-model quality.
- The small balanced fixture set is a regression suite, not a production-representative sample. Latency is a coarse local measurement, not an SLA.
- CORS is retained as metadata but does not determine server-side monitoring eligibility.

See [AI-assisted classification and evaluation](docs/ai-evaluation.md) for metric definitions, threshold tradeoffs, failure modes, human review, prompt metadata, and modeled-cost assumptions.

## License

MIT. The source catalog has its own [MIT license](https://github.com/public-apis/public-apis/blob/master/LICENSE).
