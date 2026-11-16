#!/usr/bin/env python3
"""Overnight bake-off of local LM Studio models on the golden job set.

For every model it can find on disk, in the order given below, it LOADS the model (`lms load`), runs the
golden jobs through the real review prompt once per reasoning mode, writes the results and refreshes the
report after EVERY run, then UNLOADS the model. Nothing is written to the real database, assessments or
radar: all output goes to `data/golden/bakeoff/<run-id>/`.

Reasoning modes (from each model's own capabilities in LM Studio's API):
  off      reasoning_effort "none"  (thinking switched off; ~10x faster on Qwen3.6)
  low      reasoning_effort "low"   (only models that list it, e.g. qwen3.8-27b)
  default  field omitted = the model's own default (usually full thinking; may be very slow)
A model with no reasoning setting (e.g. qwen3-4b-2507) gets a single `default` run.

Run order is stage by stage, so a partial night still gives a useful table: every `off` run first
(small models first), then `low`, then every `default` run. `--run-budget-minutes` caps one run and
`--deadline-hours` caps the whole night; either stops cleanly and the report notes the jobs done.

Golden set: data/golden/golden_jobs.json (scripts/build_golden_jobs.py). The CANDIDATE HISTORY block in
the prompt excludes the golden jobs themselves, so a model never sees the answer.

    uv run python scripts/bakeoff_models.py --plan                       # show the plan, change nothing
    caffeinate -i uv run python scripts/bakeoff_models.py                # the overnight run
    uv run python scripts/bakeoff_models.py --models qwen/qwen3-4b-2507 --limit 6    # quick smoke test
    uv run python scripts/bakeoff_models.py --report-only data/golden/bakeoff/<run-id>
    uv run python scripts/bakeoff_models.py --resume data/golden/bakeoff/<run-id>     # continue a stopped night

It takes the shared "job-hunter" run lock, so it cannot overlap a pipeline/review run that would fight it
for the model; it unloads whatever else is loaded first. Stop it with Ctrl+C (the loaded model is unloaded).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_with_lm_studio as reviewer  # noqa: E402  (reuses the real prompt text)

from job_hunter.atomic import atomic_write_text  # noqa: E402
from job_hunter.config import load_profile  # noqa: E402
from job_hunter.lm_studio_health import load_lm_studio_config  # noqa: E402
from job_hunter.review_prompt import (  # noqa: E402
    ModelVerdict,
    apply_caps,
    clean_descriptions,
    domain_definition,
    history_block,
)
from job_hunter.rootutil import add_project_argument, chdir_to_project_root  # noqa: E402
from job_hunter.runlock import RunLockHeld, run_lock  # noqa: E402

GOLDEN = Path("data/golden/golden_jobs.json")
DEFAULT_MODELS = [
    "qwen/qwen3.6-35b-a3b",       # current default (baseline)
    "qwen/qwen3.6-27b",
    "qwen/qwen3.8-27b",
    "qwen/qwen3-4b-2507",
    "qwen/qwen3-4b",
    "google/gemma-4-31b-qat",     # skipped automatically until it is on disk
]
MODE_FIELDS: dict[str, dict[str, Any]] = {"off": {"reasoning_effort": "none"}, "low": {"reasoning_effort": "low"}, "default": {}}
STAGE = {"off": 0, "low": 1, "default": 2}


# ---------------------------------------------------------------------------------------- LM Studio


def _lms() -> str:
    found = shutil.which("lms") or str(Path.home() / ".lmstudio/bin/lms")
    if not Path(found).exists():
        raise SystemExit("job-hunter: the `lms` CLI was not found (LM Studio > Developer > Install CLI).")
    return found


def _root(base_url: str) -> str:
    return re.sub(r"/v1/?$", "", base_url.rstrip("/"))


def installed_models(client: httpx.Client, root: str) -> dict[str, dict[str, Any]]:
    data = client.get(f"{root}/api/v1/models", timeout=20).json()["models"]
    return {m["key"]: m for m in data if m.get("type") == "llm"}


def modes_for(model: dict[str, Any]) -> list[str]:
    reasoning = (model.get("capabilities") or {}).get("reasoning") or {}
    options = set(reasoning.get("allowed_options") or [])
    if not options:
        return ["default"]
    modes = []
    if "off" in options:
        modes.append("off")
    if "low" in options:
        modes.append("low")
    modes.append("default")
    return modes


def build_plan(client: httpx.Client, root: str, wanted: list[str], only_modes: list[str] | None) -> tuple[list[tuple[str, str]], list[str]]:
    have = installed_models(client, root)
    skipped = [m for m in wanted if m not in have]
    runs: list[tuple[str, str]] = []
    for key in wanted:
        if key in have:
            runs += [(key, mode) for mode in modes_for(have[key]) if not only_modes or mode in only_modes]
    single = {k for k in wanted if k in have and modes_for(have[k]) == ["default"]}  # no thinking switch: fast, go first
    runs.sort(key=lambda r: (0 if r[0] in single else STAGE[r[1]], have[r[0]].get("size_bytes") or 0))
    return runs, skipped


def _run_lms(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_lms(), *args], capture_output=True, text=True, timeout=timeout, check=False)


def unload_all() -> None:
    _run_lms(["unload", "--all"], timeout=120)


def load_model(client: httpx.Client, root: str, key: str, context_length: int) -> None:
    unload_all()
    result = _run_lms(["load", key, "--identifier", key, "-c", str(context_length), "--parallel", "1", "--ttl", "21600", "-y"])
    if result.returncode != 0:
        raise RuntimeError(f"lms load {key} failed: {(result.stderr or result.stdout).strip()[-300:]}")
    for _ in range(60):
        loaded = installed_models(client, root).get(key, {}).get("loaded_instances")
        if loaded:
            return
        time.sleep(2)
    raise RuntimeError(f"{key} did not report as loaded")


# ------------------------------------------------------------------------------------------- jobs


def load_golden(limit: int | None) -> list[dict[str, Any]]:
    jobs = json.loads(GOLDEN.read_text())["jobs"]
    order = random.Random(7)
    pos = [j for j in jobs if j["group"] == "positive"]
    neg = [j for j in jobs if j["group"] == "negative"]
    neu = [j for j in jobs if j["group"] == "neutral"]
    for bucket in (pos, neg, neu):
        order.shuffle(bucket)
    interleaved: list[dict[str, Any]] = []
    for i in range(max(len(pos), len(neg))):  # balanced, so a run stopped early is still comparable
        if i < len(pos):
            interleaved.append(pos[i])
        if i < len(neg):
            interleaved.append(neg[i])
    interleaved += neu
    return interleaved[:limit] if limit else interleaved


def build_context(profile: Any, golden: list[dict[str, Any]]) -> str:
    keys = {j["key"] for j in golden}
    apps = json.loads(Path("data/applications.json").read_text()) if Path("data/applications.json").exists() else []
    fb = json.loads(Path("data/job_feedback.json").read_text()) if Path("data/job_feedback.json").exists() else []
    apps = [a for a in apps if f"{a['source_key']}:{a['job_id']}" not in keys]
    fb = [f for f in fb if f"{f['source_key']}:{f['job_id']}" not in keys]
    return domain_definition(profile) + "\n" + history_block(apps, fb)


def review(client: httpx.Client, cfg: dict[str, Any], model: str, mode: str, job: dict[str, Any], *, resume: str,
           rubric: str, context: str, description: str, threshold: int, timeout: float) -> dict[str, Any]:
    system = reviewer._SYSTEM_PROMPT.format(rubric=rubric, threshold=threshold, context=context)
    user = reviewer._USER_PROMPT.format(
        resume=resume, title=job["title"], company=job["company"], location=job.get("location_raw") or "",
        url=job.get("canonical_url") or "", description=description or "(no description available)",
    )
    body = {"model": model, "temperature": cfg.get("temperature", 0.2),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], **MODE_FIELDS[mode]}
    result: dict[str, Any] = {"attempts": 0, "secs": 0.0, "prompt_tokens": None, "completion_tokens": None, "first_try_valid": False}
    for attempt in (1, 2):  # a formatting slip gets exactly one retry; both attempts are timed and counted
        result["attempts"] = attempt
        started = time.monotonic()
        timed_out = False
        try:
            response = client.post(f"{cfg['base_url'].rstrip('/')}/chat/completions", json=body, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            message = payload["choices"][0]["message"]
            usage = payload.get("usage") or {}
            result["prompt_tokens"] = usage.get("prompt_tokens")
            result["completion_tokens"] = (result["completion_tokens"] or 0) + (usage.get("completion_tokens") or 0)
            result["reasoning_chars"] = len(message.get("reasoning_content") or "")
            content = re.sub(r"<think>.*?</think>", "", message.get("content") or "", flags=re.S)
            verdict = ModelVerdict.model_validate(reviewer._extract_json(content))
            result["verdict"] = apply_caps(verdict.model_dump(), threshold=threshold)
            result["first_try_valid"] = attempt == 1
            result.pop("error", None)
        except Exception as exc:  # noqa: BLE001 - recorded, never fatal to the night
            result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            timed_out = isinstance(exc, httpx.TimeoutException)
        result["secs"] += time.monotonic() - started
        if "verdict" in result or timed_out:
            break
    result["secs"] = round(result["secs"], 1)
    return result


# ------------------------------------------------------------------------------------- reporting


def _auc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    return round(sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg)), 3)


def summarize(run: dict[str, Any], group_of: dict[str, str], outcome_of: dict[str, str]) -> dict[str, Any]:
    done = run["jobs"]
    valid = {k: v for k, v in done.items() if "verdict" in v}
    score = lambda grp: [v["verdict"]["score"] for k, v in valid.items() if group_of.get(k) == grp]  # noqa: E731
    pos, neg = score("positive"), score("negative")
    by_outcome: dict[str, float] = {}
    for outcome in sorted(set(outcome_of.values())):
        vals = [v["verdict"]["score"] for k, v in valid.items() if outcome_of.get(k) == outcome]
        if vals:
            by_outcome[outcome] = round(statistics.mean(vals), 1)
    secs = [v["secs"] for v in done.values() if v.get("secs")]
    off = lambda grp: sum(1 for k, v in valid.items() if group_of.get(k) == grp and v["verdict"]["domain_fit"] == "off")  # noqa: E731
    return {
        "model": run["model"], "mode": run["mode"], "done": len(done), "target": run["target"],
        "stopped": run.get("stopped_reason") or "", "valid_first_try": sum(1 for v in done.values() if v.get("first_try_valid")),
        "valid_final": len(valid), "median_secs": round(statistics.median(secs), 1) if secs else None,
        "total_min": round(sum(secs) / 60, 1), "median_out_tokens": statistics.median([v["completion_tokens"] or 0 for v in done.values()]) if done else None,
        "auc": _auc(pos, neg), "neg_ge70": f"{sum(s >= 70 for s in neg)}/{len(neg)}", "pos_ge70": f"{sum(s >= 70 for s in pos)}/{len(pos)}",
        "pos_ge75": f"{sum(s >= 75 for s in pos)}/{len(pos)}", "pos_ge80": f"{sum(s >= 80 for s in pos)}/{len(pos)}",
        "neg_off": f"{off('negative')}/{len(neg)}", "pos_off": f"{off('positive')}/{len(pos)}", "mean_by_outcome": by_outcome,
    }


def write_report(out_dir: Path, golden: list[dict[str, Any]], plan: list[tuple[str, str]], note: str = "") -> None:
    group_of = {j["key"]: j["group"] for j in golden}
    outcome_of = {j["key"]: j["outcome"] for j in golden}
    runs = []
    for f in sorted((out_dir / "runs").glob("*.json")):
        runs.append(json.loads(f.read_text()))
    rows = [summarize(r, group_of, outcome_of) for r in runs]
    rows.sort(key=lambda r: (-(r["auc"] or 0), r["median_secs"] or 1e9))
    cols = ["model", "mode", "done", "target", "valid_first_try", "valid_final", "median_secs", "total_min", "median_out_tokens",
            "auc", "neg_ge70", "pos_ge70", "pos_ge75", "pos_ge80", "neg_off", "pos_off", "stopped"]
    with open(out_dir / "summary.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    # per-job matrix: one column per run, "score domain" each
    labels = [f"{r['model'].split('/')[-1]}|{r['mode']}" for r in runs]
    matrix = []
    for job in golden:
        row = {"outcome": job["outcome"], "group": job["group"], "company": job["company"], "title": job["title"][:60], "key": job["key"]}
        for label, run in zip(labels, runs, strict=True):
            v = run["jobs"].get(job["key"], {})
            verdict = v.get("verdict")
            row[label] = f"{verdict['score']} {verdict['domain_fit'][:3]}" if verdict else ("ERR" if v else "")
        matrix.append(row)
    with open(out_dir / "matrix.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["outcome", "group", "company", "title", "key", *labels])
        writer.writeheader()
        writer.writerows(matrix)
    lines = [f"# Model bake-off report ({datetime.now().astimezone():%Y-%m-%d %H:%M})", "",
             f"Golden jobs: {len(golden)} ({sum(g['group']=='positive' for g in golden)} positive, "
             f"{sum(g['group']=='negative' for g in golden)} negative, {sum(g['group']=='neutral' for g in golden)} neutral). "
             f"Runs finished or in progress: {len(runs)} of {len(plan)} planned. {note}", "",
             "AUC = chance a positive (offer/interview/applied/saved/...) outscores a negative (tagged irrelevant); 1.0 is perfect, 0.5 is chance.",
             "`neg_ge70` is the noise that still reaches 'Likely fit'; `pos_ge70/75/80` is how many jobs you wanted that stay visible; `pos_off` is wanted jobs wrongly called off-domain.", "",
             "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    lines += ["", "## Mean score by outcome", "", "| run | " + " | ".join(sorted(set(outcome_of.values()))) + " |", "|" + "---|" * (1 + len(set(outcome_of.values())))]
    for r in rows:
        lines.append(f"| {r['model'].split('/')[-1]} {r['mode']} | " + " | ".join(str(r["mean_by_outcome"].get(o, "")) for o in sorted(set(outcome_of.values()))) + " |")
    lines += ["", "## Per-job comparison (score and domain call per run; see matrix.csv)", "", "| outcome | company | title | " + " | ".join(labels) + " |", "|" + "---|" * (3 + len(labels))]
    lines += ["| " + " | ".join([m["outcome"], m["company"][:14], m["title"][:42], *[str(m[label]) for label in labels]]) + " |" for m in matrix]
    atomic_write_text(out_dir / "report.md", "\n".join(lines) + "\n")


# ----------------------------------------------------------------------------------------- driver


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS), help="comma-separated LM Studio model keys")
    parser.add_argument("--modes", default=None, help="restrict to these modes (off,low,default)")
    parser.add_argument("--limit", type=int, default=None, help="only the first N golden jobs (balanced); for smoke tests")
    parser.add_argument("--run-budget-minutes", type=float, default=90, help="stop one run after this long (default 90)")
    parser.add_argument("--deadline-hours", type=float, default=10, help="stop the whole night after this long (default 10)")
    parser.add_argument("--job-timeout", type=float, default=600, help="seconds before one request is abandoned (default 600)")
    parser.add_argument("--context-length", type=int, default=32768)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--resume", type=Path, default=None, help="continue a previous output directory")
    parser.add_argument("--report-only", type=Path, default=None, help="rebuild the report of an output directory and exit")
    parser.add_argument("--plan", action="store_true", help="print the plan and exit")
    parser.add_argument("--keep-loaded", action="store_true", help="leave the last model loaded at the end")
    add_project_argument(parser)
    args = parser.parse_args()
    chdir_to_project_root(args.project)
    if not GOLDEN.exists():
        raise SystemExit("job-hunter: no golden set; run `uv run python scripts/build_golden_jobs.py` first.")
    golden = load_golden(args.limit)
    cfg = load_lm_studio_config(Path("config/lm_studio.yaml"))
    root = _root(cfg["base_url"])
    wanted = [m.strip() for m in args.models.split(",") if m.strip()]
    only_modes = [m.strip() for m in args.modes.split(",")] if args.modes else None

    with httpx.Client() as client:
        plan, skipped = build_plan(client, root, wanted, only_modes)
        if args.report_only:
            write_report(args.report_only, golden if not args.limit else load_golden(None), plan)
            print(f"Report rebuilt: {args.report_only / 'report.md'}")
            return 0
        print(f"Golden jobs: {len(golden)}. Planned runs ({len(plan)}):")
        for key, mode in plan:
            print(f"  {key}  [{mode}]")
        if skipped:
            print(f"Skipped (not on disk, see `lms ls`): {', '.join(skipped)}")
        if args.plan:
            return 0
        out_dir = args.resume or args.out_dir or Path("data/golden/bakeoff") / datetime.now().strftime("%Y-%m-%d-T-%H-%M-%S")
        (out_dir / "runs").mkdir(parents=True, exist_ok=True)
        profile, resume = reviewer.resolve_resume(load_profile(), Path.cwd())
        rubric = reviewer._SCORING_RUBRIC_PATH.read_text(encoding="utf-8")
        context = build_context(profile, golden)
        descriptions = clean_descriptions([{**j, "source_key": j["source_key"], "job_id": j["job_id"]} for j in golden])
        deadline = datetime.now(UTC) + timedelta(hours=args.deadline_hours)
        threshold = profile.minimum_recommendation_score
        loaded: str | None = None
        failed_models: set[str] = set()
        try:
            with run_lock("job-hunter"):
                for key, mode in plan:
                    if datetime.now(UTC) >= deadline:
                        print("Deadline reached; stopping.")
                        break
                    if key in failed_models:
                        continue
                    path = out_dir / "runs" / f"{key.replace('/', '__')}__{mode}.json"
                    run = json.loads(path.read_text()) if path.exists() else {"model": key, "mode": mode, "jobs": {}, "target": len(golden)}
                    run["target"] = len(golden)
                    if len(run["jobs"]) >= len(golden) and not any("verdict" not in v for v in run["jobs"].values()):
                        continue
                    try:
                        if loaded != key:
                            print(f"\n=== loading {key} ...", flush=True)
                            load_model(client, root, key, args.context_length)
                            loaded = key
                    except Exception as exc:  # noqa: BLE001
                        print(f"  could not load {key}: {exc}; skipping its runs", flush=True)
                        failed_models.add(key)
                        continue
                    print(f"=== {key} [{mode}]", flush=True)
                    started = time.monotonic()
                    for job in golden:
                        done = run["jobs"].get(job["key"])
                        if done and "verdict" in done:
                            continue
                        if (time.monotonic() - started) / 60 > args.run_budget_minutes or datetime.now(UTC) >= deadline:
                            run["stopped_reason"] = "run budget" if datetime.now(UTC) < deadline else "deadline"
                            break
                        run["jobs"][job["key"]] = review(client, cfg, key, mode, job, resume=resume, rubric=rubric, context=context,
                                                         description=descriptions[(job["source_key"], job["job_id"])],
                                                         threshold=threshold, timeout=args.job_timeout)
                        r = run["jobs"][job["key"]]
                        v = r.get("verdict") or {}
                        print(f"  [{len(run['jobs'])}/{len(golden)}] {job['outcome'][:11]:11s} {str(v.get('score')):>4} {str(v.get('domain_fit'))[:4]:4s} "
                              f"{r['secs']:6.1f}s out {r['completion_tokens']} {job['title'][:40]}{'  ERR '+r['error'][:60] if 'error' in r else ''}", flush=True)
                        atomic_write_text(path, json.dumps(run, indent=1, ensure_ascii=False) + "\n")
                    else:
                        run.pop("stopped_reason", None)
                    atomic_write_text(path, json.dumps(run, indent=1, ensure_ascii=False) + "\n")
                    write_report(out_dir, golden, plan)
                    print(f"  report refreshed: {out_dir / 'report.md'}", flush=True)
                    nxt = next((p for p in plan[plan.index((key, mode)) + 1:]), None)
                    if nxt is None or nxt[0] != key:
                        _run_lms(["unload", key], timeout=120)
                        loaded = None
        except RunLockHeld as exc:
            print(f"job-hunter: {exc} - another job-hunter run holds the model; try again when it finishes.", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            print("\nInterrupted; unloading.", flush=True)
        finally:
            if loaded and not args.keep_loaded:
                _run_lms(["unload", "--all"], timeout=120)
            write_report(out_dir, golden, plan)
        print(f"\nDone. Report: {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
