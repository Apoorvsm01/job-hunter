from __future__ import annotations

from .models import HealthStatus, SourceHealth


def detect_field_coverage(
    health: SourceHealth, details: list, expectations: dict[str, float] | None, min_sample: int = 10,
    what: str = "fetched details",
) -> SourceHealth:
    """Flags (never fails) a source whose freshly fetched detail records stop carrying a field we
    rely on — e.g. Ford's `Category` (mapped to `department`) disappearing after an Oracle change.
    `expectations` is the company config's `expect_detail_fields`: {JobDetail field: minimum filled
    fraction}. Checked only over details fetched *this run* (a run that fetched fewer than
    `min_sample` proves nothing; `what` names the records: "fetched details", or "listing items" for
    `expect_listing_fields`), and only on an otherwise clean run, so it can't mask a worse
    status. A WARNING keeps the run's jobs but skips `mark_missing`/the count baseline, same as
    `detect_count_anomaly`; it shows in `source-status` and the radar's Collection Issues."""
    if health.status != HealthStatus.OK or not expectations or len(details) < min_sample:
        return health
    problems = []
    for field, minimum in expectations.items():
        filled = sum(1 for detail in details if getattr(detail, field, None))
        if filled / len(details) < float(minimum):
            problems.append(f"{field} filled for {filled}/{len(details)} {what} (expected >= {float(minimum):.0%})")
    if problems:
        health.status = HealthStatus.WARNING
        health.message = (
            "Detail field coverage dropped: " + "; ".join(problems)
            + " — the source's payload may have changed (see docs/SPEC.md, Field mappings)"
        )
    return health


def detect_count_anomaly(
    health: SourceHealth, previous_count: int | None, threshold: int = 20
) -> SourceHealth:
    if health.status != HealthStatus.OK or previous_count is None or previous_count < threshold:
        return health
    suspicious = health.job_count == 0 or health.job_count < previous_count * 0.30
    if suspicious:
        health.status = HealthStatus.WARNING
        health.message = f"Suspicious job-count drop: {previous_count} to {health.job_count}; prior jobs retained"
    return health
