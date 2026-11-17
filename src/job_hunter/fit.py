"""Display-only "fit tier" and "pay" indicators for the radar (`settings.radar.fit`).

Two independent things, both computed at render time from data already stored, never fed back
into scoring, filtering or `content_hash`:

- **Tier** (`top` / `likely` / None): how much attention a reviewed job deserves, from the local
  model's score and, when the assessment carries them, its structured judgments (`domain_fit`,
  `seniority_fit`, `blockers`; see `review_prompt.py`). A Dream job needs a lower score to reach
  `top`, because you already want the company/title. Assessments made before those judgments existed
  fall back to the score alone, against stricter `legacy_*` bars (their scale runs higher and nothing
  gated their domain). Nothing is hidden: a job without a tier still shows in its
  section; the tier only adds a tag and a filter chip.
- **Pay** (`ok` / `low` / None): the top of a stated USD annual range against `pay_floor_usd`,
  kept apart from fit on purpose (a declined offer for pay was still a perfect role fit). Missing
  or non-annual pay is None, never "low".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from job_hunter.config import FitConfig

_MIN_ANNUAL_USD = 1000  # below this a stated figure is an hourly rate, not an annual salary


@dataclass(frozen=True)
class FitDecision:
    tier: str | None = None  # "top" | "likely" | None
    reasons: list[str] = field(default_factory=list)
    pay: str | None = None  # "ok" | "low" | None
    pay_top: int | None = None


def pay_top_usd(job: Mapping[str, Any]) -> int | None:
    """Top of the stated annual USD range, or None (no pay, non-USD, or an hourly figure)."""
    if (job.get("salary_currency") or "USD").upper() != "USD":
        return None
    top = job.get("salary_max") or job.get("salary_min")
    if not top or top < _MIN_ANNUAL_USD:
        return None
    return int(top)


def evaluate_fit(
    job: Mapping[str, Any], assessment: Mapping[str, Any] | None, config: FitConfig, *, is_dream: bool = False
) -> FitDecision:
    top = pay_top_usd(job)
    pay = None if top is None else ("ok" if top >= config.pay_floor_usd else "low")
    if not assessment:
        return FitDecision(pay=pay, pay_top=top)
    score = assessment.get("score")
    domain = assessment.get("domain_fit")
    seniority = assessment.get("seniority_fit")
    judged = domain is not None  # reviewed by the prompt that records domain/level/blockers
    likely_min = config.likely_min_score if judged else config.legacy_likely_min_score
    top_min = config.top_min_score if judged else config.legacy_top_min_score
    if score is None or score < likely_min:
        return FitDecision(pay=pay, pay_top=top)

    blockers = assessment.get("blockers") or []
    reasons = [f"score {score}"]
    if domain == "off":
        return FitDecision(pay=pay, pay_top=top)
    clean = domain in (None, "core") and seniority in (None, "match") and not blockers
    if domain:
        reasons.append(f"{domain} domain")
    if seniority and seniority != "match":
        reasons.append(f"level {seniority} yours")
    if blockers:
        reasons.append("hard requirement unmet")
    if clean and score >= top_min:
        return FitDecision("top", reasons, pay, top)
    if clean and is_dream:
        return FitDecision("top", [*reasons, "dream"], pay, top)
    return FitDecision("likely", reasons, pay, top)
