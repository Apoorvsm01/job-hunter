#!/usr/bin/env python3
"""Build (or extend) the golden job set used to compare local review models.

The set is made of the jobs you *acted on or labelled*, snapshotted WITH their posting text so it
survives cleanup and later re-collection:

  positive  offer_declined / interviewing / interviewed_rejected / applied / rejected / withdrawn /
            saved (from the `applications` table) and radar feedback labelled `relevant`
  negative  radar feedback labelled `irrelevant`
  neutral   radar feedback labelled `okay` (kept for the matrix, excluded from the separation metrics)

`data/golden/outcome_overrides.json` adds what the tables cannot know (an interview, a declined
offer). Existing entries are never dropped or rewritten unless --refresh is given, so the file only
grows. Text comes from the jobs table, falling back to `data/cleanup-exports/*.json` for postings
cleanup already deleted. Output: data/golden/golden_jobs.json (git-ignored with the rest of data/;
back it up if you care about it). Read-only against the database.

    uv run python scripts/build_golden_jobs.py [--refresh]
"""

from __future__ import annotations

import argparse
import glob
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from job_hunter.atomic import atomic_write_text
from job_hunter.config import load_settings
from job_hunter.rootutil import add_project_argument, chdir_to_project_root

GOLDEN = Path("data/golden/golden_jobs.json")
OVERRIDES = Path("data/golden/outcome_overrides.json")
# How strongly an outcome says "this is the kind of job I want" (also the sort order).
WEIGHT = {
    "offer_declined": 1.0, "interviewing": 1.0, "interviewed_rejected": 1.0, "applied": 0.9,
    "relevant": 0.8, "rejected": 0.8, "withdrawn": 0.7, "saved": 0.6,
}
TEXT_FIELDS = (
    "source_key", "job_id", "company", "title", "department", "location_raw", "canonical_url",
    "description", "salary_min", "salary_max", "salary_currency", "posted_at", "work_arrangement",
)


def _jobs_from_db(path: Path) -> dict[tuple[str, str], dict]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return {(r["source_key"], r["job_id"]): dict(r) for r in conn.execute("SELECT * FROM jobs")}
    finally:
        conn.close()


def _jobs_from_exports() -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for f in sorted(glob.glob("data/cleanup-exports/*.json")):
        try:
            for job in json.loads(Path(f).read_text()).get("deleted_jobs", []):
                out[(job["source_key"], job["job_id"])] = job
        except (OSError, ValueError, KeyError):
            continue
    return out


def build(refresh: bool = False) -> dict:
    settings = load_settings()
    existing = {}
    if GOLDEN.exists() and not refresh:
        existing = {e["key"]: e for e in json.loads(GOLDEN.read_text())["jobs"]}
    apps = json.loads(Path("data/applications.json").read_text()) if Path("data/applications.json").exists() else []
    feedback = json.loads(Path("data/job_feedback.json").read_text()) if Path("data/job_feedback.json").exists() else []
    overrides = {k: v for k, v in json.loads(OVERRIDES.read_text()).items() if not k.startswith("_")} if OVERRIDES.exists() else {}
    db = _jobs_from_db(settings.database_path)
    exports = _jobs_from_exports()

    wanted: dict[tuple[str, str], dict] = {}
    for a in apps:
        wanted[(a["source_key"], a["job_id"])] = {"outcome": a["status"], "origin": "application"}
    for f in feedback:
        key = (f["source_key"], f["job_id"])
        if key in wanted:
            continue
        wanted[key] = {"outcome": {"irrelevant": "irrelevant", "okay": "okay", "relevant": "relevant"}.get(f["label"], f["label"]), "origin": "feedback"}
    for k, v in overrides.items():
        sk, jid = k.split(":", 1)
        wanted[(sk, jid)] = {**wanted.get((sk, jid), {"origin": "override"}), "outcome": v["outcome"], "note": v.get("note")}

    jobs, missing = dict(existing), []
    for (sk, jid), meta in sorted(wanted.items()):
        key = f"{sk}:{jid}"
        src = db.get((sk, jid)) or exports.get((sk, jid))
        if key in existing:
            existing[key].update({"outcome": meta["outcome"], "note": meta.get("note")})
            existing[key]["group"] = _group(meta["outcome"])
            existing[key]["weight"] = WEIGHT.get(meta["outcome"])
            continue
        if not src or not (src.get("description") or "").strip():
            missing.append({"key": key, **meta})
            continue
        jobs[key] = {
            "key": key, **{f: src.get(f) for f in TEXT_FIELDS}, "outcome": meta["outcome"],
            "group": _group(meta["outcome"]), "weight": WEIGHT.get(meta["outcome"]),
            "origin": meta["origin"], "note": meta.get("note"),
            "text_from": "database" if (sk, jid) in db else "cleanup-export",
        }
    payload = {
        "built_at": datetime.now(UTC).isoformat(),
        "jobs": sorted(jobs.values(), key=lambda j: (-(j["weight"] or 0), j["key"])),
        "missing_text": missing,
    }
    atomic_write_text(GOLDEN, json.dumps(payload, indent=1, default=str, ensure_ascii=False) + "\n")
    return payload


def _group(outcome: str) -> str:
    if outcome == "irrelevant":
        return "negative"
    if outcome == "okay":
        return "neutral"
    return "positive"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="rebuild every entry from the database instead of only adding new ones")
    add_project_argument(parser)
    args = parser.parse_args()
    chdir_to_project_root(args.project)
    payload = build(refresh=args.refresh)
    jobs = payload["jobs"]
    by_group = {g: sum(j["group"] == g for j in jobs) for g in ("positive", "negative", "neutral")}
    by_outcome: dict[str, int] = {}
    for j in jobs:
        by_outcome[j["outcome"]] = by_outcome.get(j["outcome"], 0) + 1
    print(f"Wrote {GOLDEN}: {len(jobs)} jobs {by_group}")
    print("  by outcome:", dict(sorted(by_outcome.items(), key=lambda kv: -kv[1])))
    print(f"  {len(payload['missing_text'])} labelled job(s) have no posting text anywhere (already deleted before cleanup protection).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
