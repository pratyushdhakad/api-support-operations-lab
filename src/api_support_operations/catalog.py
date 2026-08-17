"""Parse public-apis-style Markdown tables into a deterministic registry."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import re
from typing import Iterable


LINK_PATTERN = re.compile(r"^\[([^\]]+)\]\((https?://[^)]+)\)$")
NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
TABLE_COLUMNS = ("api", "description", "auth", "https", "cors")


@dataclass(frozen=True)
class ApiRecord:
    """One normalized API catalog entry."""

    api_id: str
    category: str
    name: str
    description: str
    documentation_url: str
    auth_type: str
    https_supported: bool | None
    cors_status: str
    monitoring_eligible: bool
    source_line: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _slug(value: str) -> str:
    normalized = NON_ALPHANUMERIC.sub("-", value.lower()).strip("-")
    return normalized or "unknown"


def _clean_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: Iterable[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _normalize_auth(value: str) -> str:
    cleaned = _clean_cell(value).lower()
    if cleaned in {"", "no", "none"}:
        return "none"
    if cleaned in {"apikey", "api key", "api_key"}:
        return "api_key"
    if cleaned == "oauth":
        return "oauth"
    if cleaned in {"user-agent", "user agent"}:
        return "user_agent"
    return _slug(cleaned)


def _normalize_https(value: str) -> bool | None:
    cleaned = _clean_cell(value).lower()
    if cleaned == "yes":
        return True
    if cleaned == "no":
        return False
    return None


def _normalize_cors(value: str) -> str:
    cleaned = _clean_cell(value).lower()
    return cleaned if cleaned in {"yes", "no"} else "unknown"


def parse_catalog(markdown: str) -> list[ApiRecord]:
    """Return normalized records from public-apis-style Markdown tables."""

    category: str | None = None
    reading_table = False
    id_counts: Counter[str] = Counter()
    records: list[ApiRecord] = []

    for line_number, raw_line in enumerate(markdown.splitlines(), start=1):
        line = raw_line.strip()

        if line.startswith("### "):
            category = line.removeprefix("### ").strip()
            reading_table = False
            continue

        cells = _split_row(line) if "|" in line else []
        normalized_header = tuple(cell.lower() for cell in cells[:5])
        if category and normalized_header == TABLE_COLUMNS:
            reading_table = True
            continue

        if not reading_table:
            continue
        if not line or line.startswith("### ") or line.startswith("**["):
            reading_table = False
            continue
        if len(cells) < 5 or _is_separator(cells[:5]):
            continue

        link_match = LINK_PATTERN.match(cells[0])
        if not link_match:
            continue

        name, documentation_url = link_match.groups()
        auth_type = _normalize_auth(cells[2])
        https_supported = _normalize_https(cells[3])
        cors_status = _normalize_cors(cells[4])
        base_id = _slug(f"{category}-{name}")
        id_counts[base_id] += 1
        api_id = base_id if id_counts[base_id] == 1 else f"{base_id}-{id_counts[base_id]}"

        records.append(
            ApiRecord(
                api_id=api_id,
                category=category,
                name=name.strip(),
                description=_clean_cell(cells[1]),
                documentation_url=documentation_url.strip(),
                auth_type=auth_type,
                https_supported=https_supported,
                cors_status=cors_status,
                monitoring_eligible=auth_type == "none" and https_supported is True,
                source_line=line_number,
            )
        )

    return sorted(
        records,
        key=lambda record: (record.category.lower(), record.name.lower(), record.api_id),
    )


def summarize_registry(records: Iterable[ApiRecord]) -> dict[str, object]:
    materialized = list(records)
    category_counts = Counter(record.category for record in materialized)
    auth_counts = Counter(record.auth_type for record in materialized)
    return {
        "api_count": len(materialized),
        "monitoring_eligible_count": sum(
            record.monitoring_eligible for record in materialized
        ),
        "category_counts": dict(sorted(category_counts.items())),
        "auth_type_counts": dict(sorted(auth_counts.items())),
    }

