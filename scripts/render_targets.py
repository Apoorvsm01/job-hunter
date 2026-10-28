"""Render the live server's /targets page: ranked cold-outreach companies from `data/targets/*.json`,
each with a Resume and a Cold-email button that exports a targeting brief and copies a ready-to-paste
skill prompt (the same flow as the radar's Resume button). Pure presentation of rows the server
loads; every dynamic string is HTML-escaped and links only ever use http(s)/mailto schemes."""

from __future__ import annotations

import html
import re

import render_radar
from render_radar import _attr, _e

from job_hunter.targets import Target

_TEMPLATE_PATH = render_radar._TEMPLATE_DIR / "targets_template.html"


def _web_href(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:(?!\d)", url):  # javascript:, data:, mailto: ... never a web link
            return ""
        url = "https://" + url
    return html.escape(url, quote=True)


def _row_html(target: Target) -> str:
    contact = target.contact
    site = _web_href(target.website)
    name = (
        f'<a class="t-name" href="{site}" target="_blank" rel="noopener">{_e(target.company)}</a>'
        if site else f'<span class="t-name">{_e(target.company)}</span>'
    )
    who = " &middot; ".join(
        part for part in (_e(contact.full_name), _e(contact.title)) if part
    )
    links = []
    if contact.email and "@" in contact.email:
        links.append(f'<a href="mailto:{_attr(contact.email)}">{_e(contact.email)}</a>')
    linkedin = _web_href(contact.linkedin)
    if linkedin:
        links.append(f'<a href="{linkedin}" target="_blank" rel="noopener">LinkedIn</a>')
    contact_html = " &middot; ".join(part for part in [who, *links] if part)
    search = f"{target.company} {target.industries}".lower()
    return (
        f'<article class="t-row" data-key="{_attr(target.key)}" data-chicago="{1 if target.chicago else 0}" '
        f'data-search="{_attr(search)}">'
        f'<div class="t-rank"><b>{target.rank}</b><span>score {target.score}</span></div>'
        f'<div>{name}'
        + ('<span class="t-tag">Chicago</span>' if target.chicago else "")
        + f'<div class="t-sub">{_e(target.industries)}</div>'
        f'<p class="t-desc">{_e(target.description)}</p>'
        + (f'<p class="t-fit"><b>Why it fits:</b> {_e(target.fit)}</p>' if target.fit else "")
        + (f'<div class="t-contact">{contact_html}</div>' if contact_html else "")
        + '<div class="t-actions">'
        '<button type="button" class="t-btn" data-kind="resume">Resume</button>'
        '<button type="button" class="t-btn secondary" data-kind="cover">Cold email</button></div>'
        "</div></article>"
    )


def render_targets_page(targets: list[Target]) -> str:
    rows = "".join(_row_html(t) for t in targets)
    chicago = sum(1 for t in targets if t.chicago)
    subhead = (
        f"{len(targets)} companies ranked against your background, {chicago} in Chicago. "
        "Resume exports a brief and copies the resume prompt; Cold email does the same for a "
        "personalized cold email to the contact."
    )
    tokens = {
        "__SUBHEAD__": _e(subhead),
        "__EMPTY_HIDDEN__": " hidden" if targets else "",
        "__ROWS__": rows,
    }
    page = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return re.sub(r"__[A-Z][A-Z0-9_]*__", lambda m: tokens.get(m.group(0), m.group(0)), page)
