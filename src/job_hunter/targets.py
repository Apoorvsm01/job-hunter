"""Ranked cold-outreach targets (companies with no posting), kept as JSON under `data/targets/`.

A target has no job description, so the resume and outreach skills are fed a *targeting brief*
written here instead: company facts, why it fits, which story to lead with and who to write to.
Python owns the retrieval and the file; the skills own the writing (and the live company
research a hyper-personalized cold email needs). Nothing here scores or invents anything: the
rank, score and fit text are whatever the JSON file says."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .jd_export import sanitize, write_numbered_text

OutreachKind = Literal["resume", "cover"]
DEFAULT_ROLE = "Product Designer"

STORY_LABELS = {
    "syncare": "SynCare (Patched Reality): longitudinal user studies for an AI-integrated EHR system, "
    "finding friction in medical data visualization. The closest related work to anything clinical.",
    "timing_perception": "Timing and perception (Woven): a fixed-distance voice prompt reached a speeding "
    "driver too late; timing it to vehicle speed fixed it in the real-car retest.",
    "zero_to_one": "Building from raw research (Woven): from a brief and raw research covering over 100 "
    "participants to 22 scenarios and the framework the AI follows.",
    "accessibility": "Accessibility (Woven): gaze and speech research uncovered physical, vision and cognitive "
    "needs, so delivery was tailored to voice, visual or both, with on-device personalization for privacy.",
    "spatial_xr": "Interfaces with nothing to touch (Omnia): spatial interfaces for Apple Vision Pro and Meta Quest.",
    "shipped_in_car": "Shipped in the car (Omnia): CarPlay and mobile apps that cut parking search time 15% "
    "and made payment 30% faster.",
    "dashboard": "Fleet dashboard (Woven): one incident taxonomy shared by an in-car cockpit and a dashboard, "
    "built from interviews with safety drivers and engineers.",
}


class TargetContact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    email: str = ""
    linkedin: str = ""

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part).strip()


class Target(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rank: int
    key: str = Field(min_length=1)
    company: str = Field(min_length=1)
    industries: str = ""
    website: str = ""
    description: str = ""
    contact: TargetContact = Field(default_factory=TargetContact)
    score: int = 0
    fit: str = ""
    lead_story: str = ""
    chicago: bool = False


class TargetNotFound(LookupError):
    pass


@dataclass(frozen=True)
class TargetBrief:
    path: Path
    relative_path: str
    created: bool
    prompt: str


def load_targets(directory: Path) -> list[Target]:
    """Every `*.json` file in `directory`, concatenated in file-name order; a key seen twice keeps its
    first row. A missing directory or no files is an empty list, never an error."""
    targets: list[Target] = []
    seen: set[str] = set()
    if not Path(directory).is_dir():
        return targets
    for path in sorted(Path(directory).glob("*.json")):
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        for row in raw.get("targets", []):
            target = Target.model_validate(row)
            if target.key not in seen:
                seen.add(target.key)
                targets.append(target)
    return sorted(targets, key=lambda t: (t.rank, t.company.lower()))


def find_target(targets: list[Target], key: str) -> Target:
    for target in targets:
        if target.key == key:
            return target
    raise TargetNotFound(key)


def render_target_brief(target: Target, *, today: date, role: str = DEFAULT_ROLE) -> str:
    story = STORY_LABELS.get(target.lead_story, "")
    contact = target.contact
    who = ", ".join(part for part in (contact.full_name, contact.title) if part) or "Not specified"
    lines = [
        role,
        "Cold outreach, no posting",
        "",
        "Summary",
        f"Company: {target.company}",
        f"Website: {target.website or 'Not specified'}",
        f"Industries: {target.industries or 'Not specified'}",
        f"Contact: {who}",
        f"Chicago-based: {'yes' if target.chicago else 'not stated'}",
        f"Brief written: {today.isoformat()}",
        "",
        "What the company does (from the startup portfolio it was found in)",
        target.description or "Not specified",
        "",
        "Why it fits the applicant",
        target.fit or "Not specified",
        "",
        "Story to lead with (from config/resume/coverletter.md story bank)",
        story or "Pick the best fit from the story bank.",
        "",
        "How to use this file",
        "There is no job posting. The resume should target a Product Designer role at this company's "
        "kind of product. A cover letter is a cold email to the contact above: research the company's "
        "recent work first (coverletter.md section 3), name one real current product or announcement, "
        "and never invent a relationship, open role or fact.",
    ]
    return "\n".join(lines) + "\n"


def export_target_brief(
    target: Target, kind: OutreachKind, *, project_root: Path, output_root: Path, today: date
) -> TargetBrief:
    """Write (or reuse) `<output_root>/<Company>/JD_<Company>_<Role>_<YYYY-MM-DD>.txt` and the prompt that
    sends the matching skill at it. Identical content the same day reuses the file."""
    company = sanitize(target.company, "Company")
    base = f"JD_{company}_{sanitize(DEFAULT_ROLE, 'Role')}_{today.isoformat()}"
    path, created = write_numbered_text(
        Path(output_root) / company, base, render_target_brief(target, today=today)
    )
    relative = Path(os.path.relpath(path.resolve(), Path(project_root).resolve())).as_posix()
    if kind == "resume":
        prompt = f"Use the resume-generator skill on {relative}"
    else:
        contact = target.contact
        recipient = contact.full_name or "the founder"
        prompt = (
            f"Use the outreach-writer skill on {relative}: cover letter as a hyper-personalized cold email "
            f"to {recipient}"
            + (f" ({contact.title})" if contact.title else "")
            + f" at {target.company}. Research their recent work first."
        )
    return TargetBrief(path.resolve(), relative, created, prompt)
