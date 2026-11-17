"""A smaller, contact-free copy of the master resume for the local-LLM review prompt.

The file on disk is never edited and the resume generator keeps using the original. This only changes
the text sent to the model:

- the header block (name and contact line) is dropped, and any email address, phone number or URL left
  elsewhere is scrubbed: the model needs none of them to score a job, and they cost tokens;
- markdown emphasis and tab padding are flattened;
- configured sections (`compact_sections`, e.g. a student-team or invited-talks section) and entries whose
  title contains a configured term (`compact_entry_terms`, e.g. `intern`) shrink to one line of
  title, employer and dates. Everything else (summary, main roles, education, skills, publications) is kept.

Pure functions, no I/O. Nothing here touches `content_hash`: the assessment cache keys on the posting.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://\S+|www\.\S+|doi:\s*\S+", re.I)
_PHONE = re.compile(r"(?<!\w)\+?\d{0,2}[\s().-]*\(?\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{4}(?!\d)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def _plain(text: str) -> str:
    """Heading/entry text without emphasis, links or tab padding, whitespace collapsed."""
    text = _LINK.sub(r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("*", "")
    text = re.sub(r"\t+", " | ", text)
    return re.sub(r"[ ]{2,}", " ", text).strip()


def _scrub(line: str) -> str:
    line = _LINK.sub(r"\1", line)
    line = _EMAIL.sub("", line)
    line = _URL.sub("", line)
    line = _PHONE.sub("", line)
    line = line.replace("**", "").replace("__", "")
    line = re.sub(r"(?<!\w)\*(?=\S)|(?<=\S)\*(?!\w)", "", line)  # italics markers, keep list bullets
    line = re.sub(r"\t+", " | ", line)
    line = re.sub(r"\|\s*(\||$)", r"\1", line)  # a separator left dangling by a removed URL
    return re.sub(r"[ ]{2,}", " ", line).rstrip(" |")


def _terms(values: Iterable[Any] | None) -> list[str]:
    return [str(v).strip().lower() for v in (values or []) if str(v).strip()]


def review_resume_view(
    text: str, *, compact_sections: Iterable[Any] | None = None, compact_entry_terms: Iterable[Any] | None = None
) -> str:
    """Return the review copy of `text` (see module docstring). An empty configuration still drops the
    header block and scrubs contact details."""
    sections = set(_terms(compact_sections))
    entry_terms = _terms(compact_entry_terms)
    lines = text.splitlines()

    # Header block: a first top-level heading (the name) whose block holds only the name or contact details, up to the
    # second top-level heading. A resume that opens directly with a real section keeps it.
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    top = [i for i, line in enumerate(lines) if re.match(r"#\s", line)]
    if first is not None and top and top[0] == first and len(top) > 1:
        block = "\n".join(lines[first:top[1]])
        only_a_name = sum(1 for line in lines[first:top[1]] if line.strip()) <= 1
        if only_a_name or _EMAIL.search(block) or _PHONE.search(block) or _URL.search(block):
            lines = lines[top[1]:]

    out: list[str] = []
    in_compact_section = False
    entry: list[str] | None = None  # the current entry's heading, subtitle, body (only while it may be condensed)
    entry_condensed = False

    def flush() -> None:
        nonlocal entry, entry_condensed
        if entry is None:
            return
        if entry_condensed:
            head = [_plain(line.lstrip("#").strip()) for line in entry if line.startswith("#")]
            out.append("- " + " | ".join(h for h in head if h))
        else:
            out.extend(_scrub(line) for line in entry)
        entry, entry_condensed = None, False

    for line in lines:
        if re.match(r"#\s", line):
            flush()
            in_compact_section = _plain(line.lstrip("#")).lower() in sections
            out.append(_scrub(line))
            continue
        if re.match(r"##\s", line):
            flush()
            title = _plain(line.lstrip("#")).lower()
            entry = [line]
            entry_condensed = in_compact_section or any(term in title for term in entry_terms)
            continue
        if entry is not None:
            entry.append(line)
        else:
            out.append(_scrub(line))
    flush()
    cleaned = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"
