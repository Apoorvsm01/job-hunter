from __future__ import annotations

from datetime import UTC, datetime

from ..models import JobDetail, JobSummary
from ..normalizer import normalize_text
from .base import JobAdapter, SchemaError

# newgrad-jobs.com is a Webflow shell: each category tab (`?k=cd` = "Creatives and Design")
# iframes a jobright.ai "minisite" (`jobright.ai/minisites-jobs/newgrad/us/<category>?embed=true`),
# a Next.js page whose __NEXT_DATA__ carries only the first 50 jobs. The page's own "load more"
# calls this public, unauthenticated JSON endpoint (found in the page's JS chunk, then replayed
# with plain httpx, no cookies):
#   POST https://jobright.ai/swan/mini-sites/list?position=<offset>&count=<n>
#   body {"category": "newgrad:us:creatives_design"}
# -> {"success":..., "result": {"total": N, "jobList": [{"jobId", "postedAt" (ms epoch),
#     "properties": {"title", "company", "location", "salary", "workModel", "qualifications", ...}}]}}
# `position` is the real offset: position=0 and position=50 return different jobs (confirmed live).
LIST_URL = "https://jobright.ai/swan/mini-sites/list"
DETAIL_URL = "https://jobright.ai/jobs/info/{id}"
PAGE_SIZE = 50


def _posted_at(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class JobrightMinisiteAdapter(JobAdapter):
    """Multi-employer aggregator, like `ycombinator.py`: `company` comes from each item's own
    `properties.company`, not the fixed `companies.yaml` value (that one is only used for
    source-health reporting).

    Listing-only by design. The per-job page (`jobright.ai/jobs/info/<id>`) does carry
    responsibilities/skills in its __NEXT_DATA__, but it rate-limits hard (a 42-page sweep at one
    request per 0.5 s got 30 empty shells and a 403), and the collector would request it for every
    recent job before the prefilter runs. So `fetch_detail` makes no request and builds the
    description from the listing's own `qualifications` text plus its salary/work-model fields.
    `url` is the jobright job page: the employer's original link is hidden behind a jobright login.
    """

    async def fetch_summaries(self) -> list[JobSummary]:
        cfg = self.company.config
        category = cfg.get("category")
        if not category:
            raise SchemaError("category is not configured")
        max_pages = int(cfg.get("max_pages", 30))
        jobs = self.begin_listing()
        seen: set[str] = set()
        total = None
        for page in range(max_pages):
            response = await self.request(
                "POST", LIST_URL, params={"position": str(page * PAGE_SIZE), "count": str(PAGE_SIZE)},
                json={"category": category},
            )
            payload = response.json()
            result = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(result, dict) or not isinstance(result.get("jobList"), list):
                raise SchemaError("jobright mini-sites response missing result.jobList")
            if total is None:
                total = int(result.get("total") or 0)
            batch = result["jobList"]
            new = 0
            for item in batch:
                job_id = str(item.get("jobId") or "").replace('"', "").strip()
                if not job_id or job_id in seen:
                    continue
                seen.add(job_id)
                jobs.append(self._summary(job_id, item))
                new += 1
            if not batch or new == 0 or (total and len(jobs) >= total):
                break
        return jobs

    def _summary(self, job_id: str, item: dict) -> JobSummary:
        props = item.get("properties") or {}
        title = str(props.get("title") or "").strip()
        company = str(props.get("company") or "").strip()
        if not title or not company:
            raise SchemaError("jobright job entry missing title/company")
        return JobSummary(
            source_key=self.source_key,
            source_platform="jobright_minisite",
            company=company,
            job_id=job_id,
            title=title,
            url=DETAIL_URL.format(id=job_id),
            location_raw=props.get("location"),
            posted_at=_posted_at(item.get("postedAt")),
            raw=item,
        )

    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        props = (summary.raw or {}).get("properties") or {}
        lines = [str(props["qualifications"])] if props.get("qualifications") else []
        if props.get("salary"):
            lines.append(f"Salary: {props['salary']}")
        if props.get("workModel"):
            lines.append(f"Work model: {props['workModel']}")
        if props.get("industry"):
            lines.append("Industry: " + ", ".join(str(i) for i in props["industry"]))
        return JobDetail(description=normalize_text("\n".join(lines)) or None)
