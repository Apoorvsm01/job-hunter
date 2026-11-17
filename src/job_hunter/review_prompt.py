"""Pure pieces of the local-LLM review prompt, kept out of `scripts/review_with_lm_studio.py` so
they are unit-testable without a model:

- `ModelVerdict`: the strict schema of the model's JSON. Its field order is the order the prompt
  asks for: the judgments (domain, seniority, blockers) come *before* the number, so the score is
  written after the model has committed to its reasoning instead of being justified afterwards.
- `apply_caps`: deterministic ceilings on the score derived from those judgments. A local model
  drifts on "should normally prevent a recommendation"; Python does not. Every clamp is written
  into `gaps`, never silent, and the model's own number is kept in the note.
- `domain_definition` / `history_block`: prompt context built at run time from the profile and
  from what the user did (applications, feedback), so the skill files stay free of personal data.
- `clean_descriptions`: per-source boilerplate removal plus a head+tail length cap (requirements
  often sit at the end, so a plain prefix cut would drop them).

Nothing here touches `content_hash`: the assessment cache keys on the posting alone.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from job_hunter.config import CandidateProfile

DomainFit = Literal["core", "adjacent", "off"]
SeniorityFit = Literal["below", "match", "above"]

CAP_OFF_DOMAIN = 49
CAP_ADJACENT = 74
CAP_BLOCKER = 69
# No ceiling for seniority: a level mismatch is shown as a tag, never used to lower a job's score by rule
# (2026-11-16: it was ranking real V&V lead roles below the "Likely fit" line). Never gate on level.

MAX_DESCRIPTION_CHARS = 6000
_TAIL_CHARS = 1500


class ModelVerdict(BaseModel):
    """Strict schema for a local model's raw JSON verdict — rejects out-of-range scores, unknown
    facet values, a missing judgment and evidence lists outside the sizes the prompt asks for.
    (Pydantic's default mode parses the string "false" to False, never to a truthy value.)
    Field order = the order the prompt demands (judgments first, score last)."""

    domain_fit: DomainFit
    seniority_fit: SeniorityFit
    blockers: list[str] = Field(default_factory=list, max_length=3)
    matches: list[str] = Field(min_length=2, max_length=4)
    gaps: list[str] = Field(min_length=1, max_length=3)
    score: int = Field(ge=0, le=100)
    recommended: bool

    @field_validator("blockers", mode="before")
    @classmethod
    def _drop_empty_blockers(cls, value: Any) -> Any:
        # "none"/"n/a"/"" are how a model says "no blocker"; they must not count as one.
        if isinstance(value, list):
            return [
                v for v in value
                if isinstance(v, str) and v.strip() and v.strip().lower() not in {"none", "n/a", "no", "null"}
            ]
        return value


def apply_caps(verdict: dict[str, Any], *, threshold: int) -> dict[str, Any]:
    """Clamp `score` to the strictest ceiling the judgments imply and re-derive `recommended`
    from the clamped score. Returns a new dict; a clamp is recorded in `gaps` (the model's own
    number included) so a lowered score is never silent."""
    out = dict(verdict)
    ceilings: list[tuple[int, str]] = []
    if out["domain_fit"] == "off":
        ceilings.append((CAP_OFF_DOMAIN, "role is off the candidate's domain"))
    elif out["domain_fit"] == "adjacent":
        ceilings.append((CAP_ADJACENT, "role is only adjacent to the candidate's domain"))
    if out["blockers"]:
        ceilings.append((CAP_BLOCKER, "unmet hard requirement: " + "; ".join(out["blockers"])))
    if ceilings:
        cap, _ = min(ceilings, key=lambda c: c[0])
        if out["score"] > cap:
            reasons = "; ".join(reason for ceiling, reason in ceilings if ceiling == cap)
            out["gaps"] = [*out["gaps"], f"Score capped at {cap} ({reasons}); model scored {out['score']}."]
            out["score"] = cap
    out["recommended"] = bool(out["recommended"]) and out["score"] >= threshold and not out["blockers"]
    return out


def domain_definition(profile: CandidateProfile) -> str:
    """What "core / adjacent / off" mean for this candidate, from the profile's own terms."""
    areas = ", ".join(profile.target_domains) or "(none listed)"
    terms = ", ".join(profile.strong_relevance_terms) or "(none listed)"
    return (
        "DOMAIN DEFINITION (for domain_fit):\n"
        f"- The candidate's target technology areas: {areas}.\n"
        f"- Terms that mark the candidate's core work: {terms}.\n"
        "- Judge the TECHNOLOGY AREA the role works on, not the job function. A manager, lead, "
        "program, integration, validation or test role inside the candidate's technology areas is "
        "core; the same function in an unrelated technology area is not.\n"
        "- core: the role's main responsibilities sit in those areas.\n"
        "- adjacent: related engineering, or only a minor share of the work is in those areas.\n"
        "- off: a different technology area. A shared job title or method (for example "
        "'validation' or 'verification') does not make a role core when the product being "
        "validated is something else.\n"
    )


_PURSUED_ORDER = {"offer": 0, "interviewing": 1, "applied": 2, "rejected": 3, "saved": 4}
_PURSUED_LABEL = {
    "offer": "received an offer",
    "interviewing": "interviewed",
    "applied": "applied",
    "rejected": "applied (employer declined)",
    "saved": "saved",
}


def _norm(value: str) -> str:
    return re.sub(r"\W+", " ", value.lower()).strip()


def history_block(
    applications: Iterable[dict[str, Any]],
    feedback: Iterable[dict[str, Any]],
    *,
    max_pursued: int = 14,
    max_rejected: int = 8,
) -> str:
    """Roles the candidate acted on, strongest first, and roles they tagged irrelevant, from the
    database. Deterministic order and size so the text is identical for every job in a run (it is
    part of the shared prompt prefix). Context only: it hints at interests, never at skills."""
    pursued: list[tuple[int, str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    # Strongest status first, so a job saved and later applied to keeps its strongest status
    # whatever order the rows arrive in.
    for row in sorted(
        applications,
        key=lambda r: (_PURSUED_ORDER.get(str(r.get("status") or ""), 99), _norm(r.get("title") or "")),
    ):
        status = str(row.get("status") or "")
        if status not in _PURSUED_ORDER:  # withdrawn etc. carry no clear signal
            continue
        key = (_norm(row.get("company") or ""), _norm(row.get("title") or ""))
        if key in seen:
            continue
        seen.add(key)
        pursued.append((_PURSUED_ORDER[status], key[1], row.get("title") or "", row.get("company") or "", status))
    pursued.sort(key=lambda r: (r[0], r[1]))
    rejected: list[tuple[str, str, str]] = []
    seen_rejected: set[tuple[str, str]] = set()
    for row in feedback:
        if row.get("label") != "irrelevant":
            continue
        key = (_norm(row.get("company") or ""), _norm(row.get("title") or ""))
        if key in seen_rejected or key in seen:
            continue
        seen_rejected.add(key)
        rejected.append((key[1], row.get("title") or "", row.get("company") or ""))
    rejected.sort()
    lines: list[str] = []
    if pursued:
        lines.append("Roles the candidate pursued (their interests; not evidence of any skill):")
        lines += [f"- {title} ({company}) — {_PURSUED_LABEL[status]}" for _, _, title, company, status in pursued[:max_pursued]]
    if rejected:
        lines.append("Roles the candidate marked irrelevant (usually off-domain):")
        lines += [f"- {title} ({company})" for _, title, company in rejected[:max_rejected]]
    if not lines:
        return ""
    return (
        "CANDIDATE HISTORY (context only: use it to judge domain and interest. The RESUME remains the "
        "only evidence of qualifications; never copy a requirement or skill from this list):\n"
        + "\n".join(lines)
        + "\n"
    )


def _trim(text: str, limit: int = MAX_DESCRIPTION_CHARS, tail: int = _TAIL_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = limit - tail
    return text[:head].rstrip() + "\n[... middle of the posting omitted ...]\n" + text[-tail:].lstrip()


def clean_descriptions(
    candidates: list[dict[str, Any]], *, threshold: float = 0.3, min_postings: int = 5, min_chars: int = 40
) -> dict[tuple[str, str], str]:
    """Description per (source_key, job_id) with paragraphs that recur across a source's
    postings (company copy, EEO, benefits) removed, then trimmed to head + tail. Only the text
    sent to the model changes; the stored description and `content_hash` are untouched."""
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in candidates:
        by_source[c["source_key"]].append(c)
    out: dict[tuple[str, str], str] = {}
    for source, group in by_source.items():
        paras = {
            c["job_id"]: [re.sub(r"[ \t]+", " ", p).strip() for p in (c.get("description") or "").split("\n") if p.strip()]
            for c in group
        }
        boiler: set[str] = set()
        if len(group) >= min_postings:
            counts: Counter[str] = Counter()
            for items in paras.values():
                counts.update({p.lower() for p in items if len(p) >= min_chars})
            cutoff = threshold * len(group)
            boiler = {p for p, n in counts.items() if n >= 2 and n >= cutoff}
        for c in group:
            kept = [p for p in paras[c["job_id"]] if p.lower() not in boiler]
            out[(source, c["job_id"])] = _trim("\n".join(kept))
    return out
