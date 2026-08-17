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

The registry will gain a reviewed monitoring-target layer containing the exact endpoint, method, timeout, expected response contract, and request-policy notes. Catalog metadata alone will never authorize a live request.

