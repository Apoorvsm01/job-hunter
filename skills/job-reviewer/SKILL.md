---
name: job-reviewer
version: 1.3.0
description: Score job-hunter's archived candidates against the user's resume, on either a local LLM (LM Studio, default — never spends cloud/agent tokens) or this calling agent itself ("Claude engine," opt-in, spends the user's own Claude usage) — resumes automatically from wherever a prior run left off regardless of which engine scored what.
compatibility: Requires uv and Python 3.11+. LM Studio required only for the local-model engine; the Claude engine needs no local model at all.
metadata:
  job_hunter:
    stage: review
  hermes:
    tags: [jobs, resume, review]
---

# Job Reviewer

Use this skill when the user wants candidates scored/reviewed against their resume — whether
that's starting a review, checking progress, or resuming one that was interrupted. For the full
search→review→radar pipeline in one go, use the `job-hunter` orchestrator skill instead; it calls
this same command.

## Engine choice — ask every time, unless already stated

There are two scoring engines. **Determine which one before doing anything else**: if the user's
own request already names one ("review with Claude," "use the local model," "LM Studio please"),
use that. Otherwise, ask them — don't default silently, and don't remember a choice from an
earlier turn as still standing for this one.

- **LM Studio (default if the user has no preference and none was asked yet in this
  conversation):** a local model, zero cloud/agent tokens, fully deterministic. **Scoring happens
  outside this agent entirely — you never score a job yourself.**
  `scripts/review_with_lm_studio.py` is a plain deterministic script (see its docstring for
  one-time LM Studio setup), not a sub-agent. Go to **Procedure A**.
- **Claude (opt-in):** this session scores each job itself, using the exact same rubric a local
  model would get, spending the user's own Claude usage instead of a local model's compute. Worth
  mentioning before committing: pending-count × (description length) roughly predicts how much of
  this turn it'll take, same way the LM Studio path's own `--status` step is meant to set
  expectations before a long run. Go to **Procedure B**.

Both engines write to the exact same store (SQLite `assessments`, keyed by `content_hash`), so
they're fully interchangeable run to run — reviewing half a batch with LM Studio and finishing the
rest with Claude (or vice versa) is safe and expected, not a special case.

## Examples

- `/job-reviewer --keyword ADAS` — engine not stated; ask, then start (or resume) reviewing the
  newest ADAS archive
- `/job-reviewer --keyword ADAS with Claude` — Claude engine, no LM Studio needed
- `/job-reviewer --keyword ADAS` (re-invoked after an interruption) — resumes automatically,
  already-scored jobs are skipped regardless of which engine scored them, never restarts from
  scratch
- `/job-reviewer --status --keyword ADAS` — check remaining/cached/total counts, no model calls,
  engine-agnostic (this count is identical either way)
- `/job-reviewer --search data/searches/adas_2026-08-20.json` — review one specific historical
  archive by exact path, bypassing keyword resolution
- `/job-reviewer` — cold start, resolves to the newest archive of any keyword (not a resume
  guarantee — pass `--keyword` whenever you already know it)

## Contract

Input:
- project path (`--project`, defaults to `$JOB_HUNTER_ROOT`/cwd)
- engine: LM Studio (default) or Claude — asked of the user per invocation, see "Engine choice" above
- keyword or archive path (`--keyword` / `--input`, defaults to the newest archive overall)
- `--status` (report-only: remaining/cached/total counts, no model calls, no changes made;
  engine-agnostic) or, for the Claude engine, `--export-pending PATH` (same counts plus the full
  resume/rubric/candidate payload to score, still no model calls)
- optional limit (`--limit`, defaults to unlimited) and `--force` (re-review even cached jobs)

Output:
- status line (`Reviewed N job(s); skipped M already-assessed (unchanged) job(s).`) or, under
  `--status`, the resolved archive path plus remaining/cached/total counts only
- persisted verdicts — SQLite's `assessments` table plus `data/assessments.json` — not a rendered
  report; this skill doesn't produce one
- counts: reviewed vs. skipped-cached vs. total eligible this run
- failures: per-job `skipped: <reason>` lines printed to stdout, never aborting the whole run
- next command: `job-radar` with the same `--keyword`, to render the scored results

## Procedure A — LM Studio engine (default)

1. Every command below takes `--project "$CLAUDE_PROJECT_DIR"` (Claude Code) — or the equivalent
   workspace path for another runtime, e.g. Hermes — so this skill works regardless of whether the
   calling process already `cd`'d into the repo.
2. Decide which archive to review: pass `--keyword` explicitly whenever you already know it (e.g.
   you — or the orchestrator step before you — just ran `job-scout` with a specific keyword); the
   no-arg default resolves to the newest archive *overall*, which can silently change if any other
   search has run since, so it's a cold-start convenience only, not a substitute for a known
   keyword. To review one specific historical run regardless of what's newest, pass `--keyword
   "..."` (resolves to that keyword's newest archive) or `--input <exact path>`. See
   `docs/skill-split-plan.md` section 4 for the full resolution rule.
3. Optionally check progress first, with no model calls and no changes made:
   ```bash
   uv run python scripts/review_with_lm_studio.py --project "$CLAUDE_PROJECT_DIR" --status [--keyword "..."]
   ```
   Report the remaining/cached/total counts to the user before committing to a full run if it's
   likely to take a while.
4. Run the review:
   ```bash
   uv run python scripts/review_with_lm_studio.py --project "$CLAUDE_PROJECT_DIR" [--keyword "ADAS,Robotics,Product Technical Leader"]
   ```
   Sends every not-yet-cached U.S.-eligible candidate to the local model **one at a time, strictly
   sequentially**, persisting each verdict immediately (SQLite plus `data/assessments.json`) as it
   goes. **This makes it fully resumable with zero extra steps**: if the run is interrupted for
   any reason (network blip, LM Studio error, the calling agent's own process/turn getting killed
   — this can happen on Hermes with a local agent under a long-running call), simply re-invoke
   this skill with the **same `--keyword`/`--input`**. Already-scored jobs are skipped
   automatically (matched by `content_hash`, not re-sent to the model), so a resumed run only
   processes what's actually left — never redo the whole thing, never lose partial progress.
   It does **not** cap how many jobs get reviewed by default — review all of them. Only pass
   `--limit` if the user explicitly asks to review fewer than all eligible candidates this run.

   If this step reports it can't reach LM Studio (exit 2, a "can't reach LM Studio at ..." stderr
   line, or `job-hunter pipeline`'s `model_unavailable` status), don't take that at face value as
   "the server is down" — run the standalone connectivity check first:
   ```bash
   uv run python scripts/check_lm_studio.py --project "$CLAUDE_PROJECT_DIR"
   ```
   This makes the identical `GET {base_url}/models` call in isolation and prints one `OK`/`FAIL
   LM Studio: ...` line. Confirmed live with Hermes: the calling agent runtime's own network path
   to `config/lm_studio.yaml`'s `base_url` can be broken (a different container/host than LM
   Studio actually runs on, a stale LAN IP, a firewall) while LM Studio itself is running fine —
   this is a false "server is down" report, not a real one, and reporting it as the latter to the
   user is misleading. Report the check's actual OK/FAIL line and its `base_url`/model-list detail
   to the user rather than guessing.
5. Report to the user how many were newly reviewed versus already cached from a prior run (the
   script's final line: `Reviewed N job(s); skipped M already-assessed (unchanged) job(s).`). No
   Claude/agent tokens are spent scoring anything — the only LLM involved in this step is the
   local one running in LM Studio.
6. Cache validity is keyed on the job's `content_hash` alone, by design — resume/model/rubric
   changes never invalidate an already-cached assessment, while any job actually sent to the model
   this run is always scored against whatever resume is on disk right now. See CLAUDE.md's
   "Working in this repo" principle on this; not something to "fix" by adding a resume-change
   trigger.
7. Run `uv run python scripts/assessments_to_csv.py --project "$CLAUDE_PROJECT_DIR"` for a
   human-readable `data/assessments.csv`.
8. This skill's job ends here — it does not render anything. To get a report (text summary and/or
   HTML radar), invoke `job-radar`, passing the same `--keyword` you used here. If compiling a
   text summary yourself instead of delegating to `job-radar`, read `data/assessments.json` (or
   `uv run job-hunter export-assessments --project "$CLAUDE_PROJECT_DIR"`) for the verdicts to
   compile from — never invent a score, match, or gap not actually present in a recorded
   assessment.

## Procedure B — Claude engine (opt-in, this agent scores each job itself)

Same archive-resolution rule as Procedure A step 2. The only thing that changes is *who* scores
each job — persistence, caching, and resumability are identical either way, because both engines
write through the exact same `record-assessment` primitive and the exact same `content_hash`-keyed
cache.

1. Export the pending set — no LM Studio required, no model call, no network at all:
   ```bash
   uv run python scripts/review_with_lm_studio.py --project "$CLAUDE_PROJECT_DIR" --export-pending /tmp/job-hunter-pending.json [--keyword "..."] [--limit N] [--force]
   ```
   This writes `{"resume_path", "resume", "rubric", "threshold", "skipped_cached", "candidates":
   [{"source_key","job_id","company","title","location","url","description"}, ...]}` — the exact
   same resume text, rubric text, and not-yet-cached candidate set Procedure A would have sent to
   the local model, boilerplate-trimmed the same way. Report the pending count (`len(candidates)`)
   and `skipped_cached` to the user before scoring a large batch — same expectation-setting
   `--status` already gives Procedure A.
2. If `candidates` is empty, report `skipped_cached` and stop — nothing to do.
3. Score each candidate **one at a time**, in list order (mirrors Procedure A's strictly-sequential
   design — there's no reason to parallelize and every reason not to: it keeps behavior and
   resumability identical between engines). For each one, apply the exported `rubric` text and the
   same evidence standard Procedure A's local model is held to — this is not a lighter-touch
   pass just because it's cheaper to run:
   - Score 0-100 using the exact calibration bands in the rubric (90-100 exceptional, 80-89
     strong, 75-79 good, 60-74 partial, 40-59 weak, 0-39 poor).
   - `recommended` is true only when score ≥ the exported `threshold` **and** no clearly unmet hard
     requirement makes the candidate unsuitable — a high score with one disqualifying hard
     requirement is not recommended.
   - Never infer or invent experience, tools, certifications, or scope the resume doesn't
     explicitly establish; an absent qualification is "not evidenced," not assumed absent or
     assumed present.
   - Do not award points for location — U.S. eligibility is already established upstream.
   - `matches`/`gaps`: as many concrete, evidence-based items as the job genuinely supports — there
     is no database-enforced minimum, unlike the local model's own stricter self-check (2-4/1-3),
     so a job with no real description text (some listings genuinely have none) gets an honest
     low-confidence entry saying exactly that, never a padded-out fabricated match.
4. Persist that verdict immediately, before moving to the next candidate — this is what makes an
   interrupted Claude-engine run exactly as resumable as Procedure A:
   ```bash
   uv run job-hunter record-assessment --project "$CLAUDE_PROJECT_DIR" --payload '{"source_key":"...","job_id":"...","company":"...","title":"...","url":"...","score":87,"recommended":true,"matches":["..."],"gaps":["..."],"resume_path":"<the exported resume_path>"}'
   ```
   `content_hash` is never supplied — the CLI always derives it server-side from the job's current
   stored content, so a job whose posting changes after this scoring is correctly treated as
   unassessed again next time, same as Procedure A.
5. After the last candidate, report the same shape of summary Procedure A's final line gives:
   how many were newly reviewed this run vs. already cached. Then run
   `uv run python scripts/assessments_to_csv.py --project "$CLAUDE_PROJECT_DIR"` and proceed to
   step 8 above (render via `job-radar`) — identical to Procedure A from here on.
6. If interrupted partway through the scoring loop, simply re-invoke from step 1 — already-recorded
   verdicts are cached by `content_hash` exactly like Procedure A, so the re-exported pending file
   will only contain what's genuinely still unscored.
