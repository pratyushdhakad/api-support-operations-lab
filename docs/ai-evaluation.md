# AI-assisted incident classification and evaluation

Day 4 adds a provider-agnostic classification boundary, an offline reference baseline, and a reproducible evaluation harness. It consumes Day 3 incident artifacts without changing their contract. The committed path makes no external request and needs no API key.

## Classification boundary

`IncidentClassifier` accepts one sanitized `ClassificationInput` and returns:

| Field | Meaning |
|---|---|
| `failure_category` | Authentication, availability, latency degradation, rate limiting, schema drift, or `unknown` |
| `priority` | Day 3 policy priority (`SEV-1` through `SEV-3`) or `UNASSESSED` |
| `summary` | Short deterministic handoff statement |
| `recommended_owner` | Owner from the reviewed routing policy, or `Human triage` |
| `confidence` | Candidate confidence used by the review threshold |
| `review_state` | `auto_classified` or `human_review_required` |
| `abstention_reason` | Every reason automation declined an unattended decision |
| `prompt_metadata` | Provider, model, classifier version, prompt version/hash, and external-call flag |
| `modeled_usage` | Estimated tokens and explicitly modeled cost; never an invoice or savings claim |

The `DeterministicIncidentClassifier` is the committed reference provider. It uses structured status, error, detector, severity, and owner signals. A future model adapter can implement the same protocol, but it must preserve validation, sanitization, review states, usage reporting, and the offline test path.

This baseline does not demonstrate language-model quality. Because it receives the reviewed Day 3 detector signal, it primarily evaluates normalization, confidence policy, routing, summaries, abstention, and provider-interface behavior.

## Reproducible evaluation

`data/classification_evaluation.json` contains 12 labeled synthetic cases. It covers all five operational failure categories, explicit unknown input, all priority outcomes, both reviewed owners, low-confidence review, and intrinsic abstention. It contains no customer, employer, credential, or private operational data.

The evaluation reports:

- exact accuracy for category, priority, owner, review state, and summary;
- category accuracy on answered cases;
- overall category accuracy with abstentions counted as incorrect;
- macro F1 with abstentions counted as false negatives;
- precision, recall, F1, support, and answered count for every operational class;
- coverage and abstention rate at confidence thresholds `0.00`, `0.70`, `0.85`, and `0.95`;
- locally observed classifier latency in coarse buckets; and
- modeled tokens and cost.

At the reviewed `0.85` threshold, the committed baseline answers 10 of 11 operationally labeled cases: coverage is `0.9091`, accuracy on answered cases is `1.0`, and macro F1 with abstentions as false negatives is `0.96`. These are synthetic fixture results, not production performance or a general AI benchmark. The unknown case is excluded from operational-category metrics and retained to test review behavior.

Latency uses local wall-clock duration, but only `<1 ms`, `1-<5 ms`, `5-<20 ms`, `20-<100 ms`, or `>=100 ms` buckets are committed. Bucketing keeps artifacts stable while making clear that this is a local baseline measurement, not a provider SLA or production latency claim.

## Confidence and human review

The operating threshold is `0.85`. Automation requires human review when any of these conditions is true:

- confidence is below the threshold;
- the category is `unknown`;
- priority is absent or invalid;
- owner is absent or outside the reviewed routing policy.

An operator should compare the proposed category and priority with the incident evidence, confirm ownership, check current provider documentation where relevant, and record any correction before action. Reviewers must not paste credentials, raw response bodies, customer records, or private operational context into a model. A classification is decision support; Day 3 evidence and the accountable human remain authoritative.

## Failure modes

| Failure mode | Control and expected response |
|---|---|
| Ambiguous or novel signal | Return `unknown`, abstain, and route to human triage. |
| Low-confidence generic outage | Preserve the candidate but require review below the threshold. |
| Invalid priority or owner | Use `UNASSESSED` or `Human triage`; never invent an assignment. |
| Prompt or model behavior changes | Compare prompt hash, prompt version, classifier version, and evaluation artifacts before adoption. |
| Class imbalance or missing class | Inspect per-class support and F1; do not rely on aggregate accuracy alone. |
| Confidently wrong output | Sample human review remains necessary; add a sanitized labeled regression before changing policy. |
| Malicious text in evidence | Treat evidence as data, constrain output fields, and never let model text execute tools or actions. |
| Cost or token drift | Re-run the same fixtures and compare modeled usage under a versioned pricing assumption. |
| Sensitive data exposure | Reject private inputs; committed fixtures and artifacts are synthetic and contain no credentials. |

## Transparent modeled cost

Token counts use a deterministic estimate: configured prompt tokens plus one token per four serialized input/output characters, rounded up. Cost is:

`modeled tokens × illustrative USD per-million-token rate ÷ 1,000,000`

The versioned policy uses an illustrative `$0.15` input and `$0.60` output rate per million tokens. The six committed Day 3 classifications model `721` input tokens, `305` output tokens, and `$0.00029115` total. The 12-case evaluation models `$0.00057705`. No provider was called, no money was spent by this pipeline, and no realized cost or savings is claimed.

## Metadata and privacy

Every classification records `deterministic-baseline-1.0.0`, prompt version `incident-triage-v1`, and the SHA-256 hash of the repository prompt template. Metadata intentionally excludes credentials, environment variables, raw response bodies, and private data. `external_api_called` is `false` for the committed provider.

Run the complete offline flow with `make pipeline`, or rebuild only Day 4 after incident artifacts exist with `make evaluate`.
