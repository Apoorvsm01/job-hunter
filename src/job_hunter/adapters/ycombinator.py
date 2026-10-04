from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

from ..models import JobDetail, JobSummary
from ..normalizer import normalize_text
from .base import JobAdapter, SchemaError

# workatastartup.com (YC's "Work at a Startup" board) server-renders every page — role-
# filtered listings and job detail alike — via Inertia.js: a full JSON snapshot of that
# page's props is embedded in the root <div data-page="...">, HTML-entity-escaped (&quot;
# etc., a single html.unescape undoes it — simpler than jobs.apple.com's JS-string-literal
# double-escaping). A plain unauthenticated GET with a real browser-like Accept header
# already returns this; only the "Apply" action itself redirects to a YC account login
# (account.ycombinator.com) — collection and even the human-facing detail page need no
# credentials at all, confirmed by curling both with no session/cookies.
_DATA_PAGE = re.compile(r'data-page="([^"]*)"')

BASE_URL = "https://www.workatastartup.com"

# Confirmed live: this collector's shared httpx client only sets a User-Agent (see
# collector.py), and Rails answers a bare */* Accept with 406 here (looks bot-blocked —
# easy to mistake for needing stealth_html) or a 302 toward account.ycombinator.com. A
# real browser-shaped Accept header alone is what flips it to a clean unauthenticated 200
# with the full data-page payload, no cookies/session involved.
_HEADERS = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _extract_page_props(text: str) -> dict:
    match = _DATA_PAGE.search(text)
    if not match:
        raise SchemaError("workatastartup.com page missing data-page attribute")
    try:
        return json.loads(html.unescape(match.group(1)))["props"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise SchemaError("workatastartup.com data-page is not valid JSON") from exc


class YCombinatorAdapter(JobAdapter):
    """Unlike every other adapter, this source is a multi-employer aggregator: each item
    in the listing names its own hiring startup (`companyName`), which this adapter sets
    directly on `JobSummary.company` per job — deliberately overriding the usual
    one-company-per-source_key convention (every other adapter sources `company` from
    `self.company.company`, the fixed config value; see collector.py/config.py, which
    never re-derive or correct it, so this per-item override is the only path). One
    source_key ("ycombinator") represents the whole board; `self.company.company`
    ("Y Combinator (Work at a Startup)") is only ever used for source-health reporting.
    """

    async def fetch_summaries(self) -> list[JobSummary]:
        cfg = self.company.config
        list_url = cfg.get("list_url")
        if not list_url:
            raise SchemaError("list_url is not configured")
        max_pages = int(cfg.get("max_pages", 30))

        all_items: list[dict] = []
        seen_ids: set[str] = set()
        total = None
        page = 1
        while page <= max_pages:
            params = {} if page == 1 else {"page": str(page)}
            response = await self.request("GET", list_url, params=params, headers=_HEADERS)
            props = _extract_page_props(response.text)
            items = props.get("jobs")
            if items is None:
                raise SchemaError("workatastartup.com listing missing props.jobs")
            if total is None:
                total = int(props.get("totalJobsCount") or 0)
            if not items:
                break
            new_on_page = 0
            for item in items:
                job_id = str(item.get("id") or "").strip()
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                all_items.append(item)
                new_on_page += 1
            if new_on_page == 0 or (total and len(all_items) >= total):
                break
            page += 1

        jobs: list[JobSummary] = []
        for item in all_items:
            job_id = str(item["id"])
            title = str(item.get("title") or "").strip()
            company_name = str(item.get("companyName") or "").strip()
            if not title or not company_name:
                raise SchemaError("workatastartup.com job entry missing title/companyName")
            jobs.append(
                JobSummary(
                    source_key=self.source_key,
                    source_platform="ycombinator",
                    company=company_name,
                    job_id=job_id,
                    title=title,
                    url=urljoin(BASE_URL, f"/jobs/{job_id}"),
                    location_raw=item.get("location"),
                    employment_type=item.get("jobType"),
                    department=item.get("roleType"),
                )
            )
        return jobs

    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        response = await self.request("GET", summary.url, headers=_HEADERS)
        props = _extract_page_props(response.text)
        job = props.get("job")
        if not job:
            return JobDetail()
        description = job.get("descriptionHtml")
        skills = job.get("skills") or []
        extra = ""
        if skills:
            extra = "\n\nSkills: " + ", ".join(str(s) for s in skills)
        if job.get("minExperience"):
            extra += f"\nMinimum experience: {job['minExperience']}"
        return JobDetail(
            description=normalize_text((description or "") + extra) or None,
            location_raw=job.get("location") or summary.location_raw,
            employment_type=job.get("jobType") or summary.employment_type,
        )
