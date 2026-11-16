"""Deterministic detection of an explicit salary/pay figure mentioned in a posting —
the same evidence-based pattern as `sponsorship.py`: purely informational, never a
filter (`passes_prefilter` never calls this), defaulting to no evidence whenever
nothing matches rather than guessing.

Unlike sponsorship's curated phrase list, a single regex anchored on a real range (two
numbers straddling a "-"/"–"/"—"/"to", at least the first one carrying a "$") is enough
here and was validated directly against live descriptions (confirmed against real GM,
Honda, Ford, and Torc Robotics postings, and re-checked across the full stored job pool
before shipping — ~6,700 of ~30,000 active jobs match, and a random sample turned up no
false positive that wasn't a genuine compensation range). A bare single dollar figure is
deliberately NOT matched on its own — confirmed live as a real false-positive risk the
same way bare "sponsor" was for sponsorship.py: Ford's own benefits boilerplate mentions
"Life Insurance of $3,000" and "Accidental Death and Dismemberment of $1,500", neither a
salary. Every live salary mention actually found (GM's "$76,100.00 to $114,300.00",
Honda's hourly "$37.13 - $42.43", Ford's "$72,480-121,440" — note the second number
carries no "$" at all, which is why it's optional on that side only — and Torc's
Greenhouse-templated "$177,300 — $212,800 USD") is already two-sided, so requiring a
second number costs no real recall while ruling out that whole class of false positive.

Multi-range postings (~24% of postings with pay: Nvidia per Level, Microsoft/Intuitive per
region, Stryker per locality tier, Uber/Rivian per city) state several ranges in one passage.
Ranges within `_GROUP_WINDOW` characters of each other and of the same kind (both hourly or both
annual) are grouped: `min_value`/`max_value` are the smallest low and largest high across them
("for reference"), `evidence` is that overall span, and every range is kept in `tiers` with its
own wording ("168,000 USD - 264,500 USD for Level 4") so the radar can show each Level/region.

One more real trap found the same way: dozens of Caterpillar/Nissan Workday postings for
hourly/union roles carry an unfilled compensation-template field that renders as a
literal "$0.00 - $0.00" — not a real range, and never surfaced as one."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_TAG = re.compile(r"<[^>]+>")
# Zero-width/invisible characters some ATS templates leave between a "$" and its number
# or around the dash (confirmed live on Toro's "between \u200b$84,300 - \u200b$105,400").
_INVISIBLE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")

# Never ends in a comma: "$240,000," (a sentence comma) must not be part of the number.
_NUM = r"\d(?:[\d,]*\d)?(?:\.\d+)?"
# After a number (and an optional "K"): reject a trailing digit or a magnitude word, so
# "$98 billion", "$300M" or "$100K to $10M+" (company size/spend boilerplate) never reads as pay.
_END = r"(?:\s?[kK]\b)?(?!\d|\s?(?:[MmBb]\b|million|billion|bn\b))"
_FIRST = rf"\$\s?{_NUM}{_END}"
_SECOND = rf"(?:\$\s?)?{_NUM}{_END}"
_UNIT_WORDS = (
    r"(?:/\s?(?:hour|hr|year|yr)|per\s+(?:hour|year)|an\s+hour|a\s+year|hourly|annually|annual|USD)\.?"
)
_RANGE = re.compile(
    # "$X - $Y", "$X to $Y", "$X ~ $Y". The second "$" is optional ("$72,480-121,440") and a
    # unit/currency may follow either number ("$145/hr - $180/hr", "USD $216,000 per year -
    # USD $240,000 per year").
    rf"{_FIRST}(?:\s*{_UNIT_WORDS})?\s*(?:-|–|—|~|to)\s*(?:USD\s*)?{_SECOND}(?:\s*{_UNIT_WORDS})?"
    # "between $X and $Y": "and" separates only right after "between", with a "$" on both
    # sides, so "$5 and $10 gift card" or "$X and $Y in benefits" never matches.
    # No "$" at all, the currency is spelled out ("184,000 USD - 287,500 USD", NVIDIA;
    # "USD 120,000 - 150,000"). The code must sit on the first number, so a bare
    # "100,000 - 200,000" (not obviously money) still never matches.
    rf"|(?<![\w$.,]){_NUM}{_END}\s*USD\s*(?:-|–|—|~|to)\s*(?:USD\s*)?{_NUM}{_END}(?:\s*USD\b)?"
    rf"|\bUSD\s*{_NUM}{_END}\s*(?:-|–|—|~|to)\s*(?:USD\s*)?{_NUM}{_END}"
    rf"|\bbetween\s+{_FIRST}(?:\s*{_UNIT_WORDS})?\s+and\s+(?:USD\s*)?{_FIRST}(?:\s*{_UNIT_WORDS})?",
    re.I,
)
_NUMBER = re.compile(rf"({_NUM})(\s?[kK]\b)?")
# Ranges this close (characters, after tag stripping) belong to the same pay passage.
_GROUP_WINDOW = 300
_TIER_LABEL = re.compile(r"\b(Level|Grade|Band|Tier|Region|Zone)\s*([A-Za-z]?\d+)", re.I)
_TIER_TAIL = 60


@dataclass(frozen=True)
class SalaryTier:
    """One range of a multi-range posting. `label` is a Level/Grade/Band/Tier/Region/Zone token
    found in its own wording, if any; `text` is that wording, trimmed of dangling connectors."""

    low: float
    high: float
    text: str
    label: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"label": self.label, "low": self.low, "high": self.high, "text": self.text}


@dataclass(frozen=True)
class SalaryDecision:
    evidence: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    tiers: tuple[SalaryTier, ...] = ()


def _money(value: float) -> str:
    return f"${value:,.0f}" if value == int(value) else f"${value:,.2f}"


def _tier_text(text: str, start: int, end: int, next_start: int | None) -> str:
    """The range's own wording plus a short tail ("... for Level 4"), cut at the next range or the
    end of the sentence, with dangling "and"/commas removed."""
    stop = min(end + _TIER_TAIL, next_start if next_start is not None else len(text))
    snippet = text[start:stop]
    sentence_end = re.search(r"(?<=[A-Za-z0-9)])\.(?:\s|$)|;|\n", snippet[end - start :])
    if sentence_end:
        snippet = snippet[: end - start + sentence_end.start()]
    return re.sub(r"(?:[,;:\s]|\band\b|\bor\b)+$", "", snippet, flags=re.I).strip()


def _tier_label(snippet: str) -> str | None:
    match = _TIER_LABEL.search(snippet)
    return f"{match.group(1).title()} {match.group(2).upper()}" if match else None


def _value(number: str, k: str | None) -> float:
    value = float(number.replace(",", ""))
    # "$115K" is thousands; "$136,000k" is a typo for 136,000, not 136 million.
    return value * 1000 if k and value < 1000 else value


def evaluate_salary(description: str | None) -> SalaryDecision:
    # Descriptions are raw HTML, same reasoning as sponsorship.py: strip tags first so a
    # tag sitting between the two numbers (or before/after) can't defeat the pattern.
    # Also unescape entities — confirmed live on Torc Robotics' Greenhouse postings,
    # whose pay range renders as two <span> tags separated by a third holding a literal
    # "&mdash;" (not a real "—" character) — an em/en-dash entity is otherwise invisible
    # to the "-"/"–"/"—" separator alternatives below.
    text = " ".join(_TAG.sub(" ", _INVISIBLE.sub("", html.unescape(description or ""))).split())
    # First *valid* range wins: a match that parses to a non-range (an unfilled
    # "$0.00 - $0.00", or a high below the low) is skipped, not allowed to hide a real one.
    found: list[tuple[re.Match[str], float, float]] = []
    for match in _RANGE.finditer(text):
        numbers = _NUMBER.findall(match.group(0))
        if len(numbers) < 2:
            continue
        low = _value(*numbers[0])
        high = _value(*numbers[1])
        if numbers[0][1] and not numbers[1][1] and high < 1000:
            high *= 1000  # "$130k-180" means 130k to 180k
        if low == 0 and high == 0:
            continue
        if low > high:
            # A typo'd posting ("$130,000- $145,00", "$100,0000 - $130,000"): real pay text
            # worth showing as evidence, but the parsed numbers are untrustworthy, so
            # leave min/max empty. With a "K" involved ("$50K to $30") it is far more
            # likely not pay at all, so skip it.
            if numbers[0][1] or numbers[1][1]:
                continue
            if not found:
                return SalaryDecision(" ".join(match.group(0).split()))
            continue  # a later typo'd range never overrides or joins a good first one
        if found:
            first_low = found[0][1]
            if match.start() - found[-1][0].end() > _GROUP_WINDOW or (first_low < 1000) != (low < 1000):
                break  # a different passage, or a different kind of figure (hourly vs annual)
        found.append((match, low, high))
    if not found:
        return SalaryDecision()
    if len(found) == 1:
        match, low, high = found[0]
        return SalaryDecision(" ".join(match.group(0).split()), low, high)
    tiers = []
    for index, (match, low, high) in enumerate(found):
        next_start = found[index + 1][0].start() if index + 1 < len(found) else None
        wording = _tier_text(text, match.start(), match.end(), next_start)
        tiers.append(SalaryTier(low, high, wording, _tier_label(wording[match.end() - match.start() :])))
    lowest = min(t.low for t in tiers)
    highest = max(t.high for t in tiers)
    return SalaryDecision(f"{_money(lowest)} - {_money(highest)}", lowest, highest, tuple(tiers))
