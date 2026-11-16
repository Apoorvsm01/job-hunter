"""Deterministic "dream job" tagging for the radar — display-only, never a filter.

A job is a dream job when ANY configured rule matches (`config.py`'s `DreamConfig`):

- **company** — the employer's name or source key equals a listed company (case-insensitive). A
  big employer's sub-brand counts too: Google's careers pages label each posting with its
  employer ("Google", "YouTube", "DeepMind"), so listing "Google DeepMind" (or just "DeepMind")
  matches DeepMind postings under the `google` source and not the rest of Google;
- **title** — the title contains a listed term as a whole word ("lead" matches "Lead Engineer"
  and "Tech Lead", never "Leadership" or "Misleading"). `weak_title_terms` (e.g. "senior") are
  too common to mean "dream" alone: a job matching only those is the lighter "Dream-ish" tier.
  `title_exclusions` phrases ("project manager") cancel the title rules for that job, which is
  what lets a broad term like "manager" in without tagging every Project/Product Manager;
- **level** — for a source whose postings state a job level (`DreamConfig.levels`, e.g. Ford's
  `fordcareers.co/LL6`), the highest level found is >= the configured minimum;
- **salary** — a published USD salary whose top of range is >= `min_salary_usd`. A job with no
  salary simply cannot qualify on this rule; a missing salary never disqualifies it from the
  others.

Same structured-verdict pattern as `location.py`/`sponsorship.py`: `evaluate_dream` returns the
evidence ("title: supervisor") so the report can show *why* a row was tagged. It never excludes,
ranks, or alters a score — a loose rule just tags a few extra rows, which is the cheap failure.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from job_hunter.config import DreamConfig


@dataclass(frozen=True)
class DreamDecision:
    """`tier`: "dream" (a strong rule matched), "weak" (only a weak title term matched) or None."""

    tier: str | None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_dream(self) -> bool:
        return self.tier == "dream"

    @property
    def is_weak(self) -> bool:
        return self.tier == "weak"


_NOT_DREAM = DreamDecision(None)


def _norm(text: str | None) -> str:
    return " ".join((text or "").casefold().split())


_EMPLOYER_LABEL = re.compile(r"corporate_fare(.{1,40}?)place")


def _employer_names(job: Mapping[str, Any]) -> set[str]:
    """Normalized names this job can be listed under: company, source key, and — when the
    scraped page header carries an employer label (Google's `corporate_fare<Employer>place`) —
    that sub-brand alone and prefixed with the company ("Google DeepMind")."""
    names = {_norm(job.get("company")), _norm(job.get("source_key"))}
    match = _EMPLOYER_LABEL.search(job.get("description") or "")
    if match:
        label = _norm(match.group(1))
        names |= {label, _norm(f"{job.get('company') or ''} {label}")}
    names.discard("")
    return names


def evaluate_dream(job: Mapping[str, Any], config: DreamConfig | None) -> DreamDecision:
    """`job` is a candidate/archive dict (company, source_key, title, salary_min/max/currency)."""
    if config is None or not config.enabled:
        return _NOT_DREAM
    reasons: list[str] = []

    companies = {_norm(c): c.strip() for c in config.companies if _norm(c)}
    matched = [name for name in companies if name in _employer_names(job)]
    if matched:
        reasons.append(f"company: {companies[matched[0]]}")

    title = job.get("title") or ""

    def _phrase(text: str) -> str:
        return rf"(?<!\w){re.escape(text.strip())}(?!\w)"

    excluded = any(e.strip() and re.search(_phrase(e), title, re.IGNORECASE) for e in config.title_exclusions)

    def _hits(terms: list[str]) -> list[str]:
        if excluded:
            return []
        return [
            t.strip().casefold() for t in terms
            if t.strip() and re.search(rf"(?<!\w){re.escape(t.strip())}(?!\w)", title, re.IGNORECASE)
        ]

    reasons.extend(f"title: {t}" for t in _hits(config.title_terms))

    rule = config.levels.get(str(job.get("source_key") or ""))
    if rule is not None:
        found = [int(n) for n in re.findall(rule.pattern, job.get("description") or "", re.IGNORECASE)]
        if found and max(found) >= rule.min:
            reasons.append(f"level: {rule.label}{max(found)}")

    if config.min_salary_usd is not None and (job.get("salary_currency") or "USD").upper() == "USD":
        top = job.get("salary_max") or job.get("salary_min")
        if top is not None and top >= config.min_salary_usd:
            reasons.append(f"salary: ${top:,.0f}")

    if reasons:
        return DreamDecision("dream", tuple(reasons))
    weak = _hits(config.weak_title_terms)
    return DreamDecision("weak", tuple(f"title: {t}" for t in weak)) if weak else _NOT_DREAM
