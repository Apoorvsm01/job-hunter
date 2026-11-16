"""Compact capture of the source data the typed `Job` fields don't keep.

Each adapter maps a handful of fields by hand (title, location, description, ...) and everything
else in the response used to be discarded — so a later "we should have kept X" (a deadline, a
job family, a requisition type) meant re-fetching every job's detail. `jobs.extras` keeps the rest:
`{"listing": {...}, "detail": {...}}`, JSON, display/analysis-only (never a filter, never part of
`content_hash`, never in an archive — `Job.extras` is excluded from dumps).

Size is bounded on purpose (descriptions are already 98% of the database): empty values are
dropped, as are the description text fields the job already stores (by key) and any other string
longer than `MAX_STRING` (its key is listed under `_omitted_long` so you can see it existed).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

MAX_STRING = 2000
MAX_JSON_BYTES = 20_000


def _compact(value: Any, max_str: int, omitted: list[str], key: str = "") -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            c = _compact(v, max_str, omitted, str(k))
            if c not in (None, "", [], {}):
                out[str(k)] = c
        return out
    if isinstance(value, (list, tuple)):
        items = [c for v in value if (c := _compact(v, max_str, omitted, key)) not in (None, "", [], {})]
        return items
    if isinstance(value, str):
        if len(value) > max_str:
            if key and key not in omitted:
                omitted.append(key)
            return None
        return value.strip()
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)


def compact_extras(
    data: Any, *, skip_keys: Iterable[str] = (), max_str: int = MAX_STRING
) -> dict[str, Any]:
    """Compact one response object (listing item or detail payload). `skip_keys` are top-level
    keys already stored elsewhere (the description fields). Returns {} for non-dict input."""
    if not isinstance(data, dict):
        return {}
    skip = set(skip_keys)
    omitted: list[str] = []
    out = _compact({k: v for k, v in data.items() if k not in skip}, max_str, omitted)
    if omitted:
        out["_omitted_long"] = sorted(omitted)
    return out


def build_extras(listing: dict[str, Any] | None, detail: dict[str, Any] | None) -> dict[str, Any] | None:
    """Combine both parts; shrinks long strings further if the result would be oversized."""
    combined = {name: part for name, part in (("listing", listing), ("detail", detail)) if part}
    if not combined:
        return None
    if len(json.dumps(combined, ensure_ascii=False)) > MAX_JSON_BYTES:
        combined = {
            name: compact_extras(part, max_str=200) for name, part in combined.items()
        }
        combined = {name: part for name, part in combined.items() if part}
    return combined or None


def description_keys(config: dict[str, Any]) -> list[str]:
    """Top-level keys of the description fields an adapter config already maps into `description`."""
    keys: list[str] = []
    for name in ("detail_description_path", "listing_description_path"):
        value = config.get(name)
        for path in value if isinstance(value, list) else [value]:
            if isinstance(path, str) and path:
                keys.append(path.split(".")[0])
    keys.append("description")
    return keys
