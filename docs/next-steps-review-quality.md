# Next steps: review quality, speed and radar noise

Written 2026-11-15 to resume work later. Goal: fewer, clearer "worth my time" jobs on the radar
without losing real ones, and a faster local review. Principle that governs everything below:
**prefer a false negative over a silently lost job**, so new signals rank and tag; they do not gate.

## State at the end of this session (all committed and pushed to `origin/dev`)

- **Review prompt rewrite** (`src/job_hunter/review_prompt.py`, `scripts/review_with_lm_studio.py`,
  `job-reviewer` skill 1.3.0, migration v9): `domain_fit`/`seniority_fit`/`blockers` before the score,
  deterministic caps (off 49, adjacent 74, blocker 69, level mismatch 74), a profile-derived domain
  definition, a history block (what you applied to / were interviewed for / tagged irrelevant),
  boilerplate-stripped and head+tail-trimmed descriptions.
- **Fit tiers and pay tag** (`src/job_hunter/fit.py`, `settings.radar.fit`, enabled in the local
  `config/settings.yaml`): "Top pick" / "Likely fit" tags + chips and a separate pay tag. Needs a live
  radar server restart to show up there; a static render picks it up directly.
- **Cleanup keeps jobs you acted on** (applications or feedback labels).
- Test suite: 1185 passing.

## Measured on a 38-job sample (new prompt, `qwen/qwen3.6-35b-a3b`)

Sample = 14 acted-on + 14 irrelevant + 10 other previously-75+ jobs. Harness: `data/scratch/prompt_check.py`
(run from the repo root; output `data/scratch/prompt_check.json`; only calls LM Studio, writes no real data).

- 38/38 valid JSON, median 46 s per job.
- All 14 irrelevant jobs judged `off` domain, max score 48 (two that scored 78/82 before now score 48/45).
- Acted-on jobs: 9 of 14 at >= 70, 6 of 14 at >= 75, 2 of 14 at >= 80. The new prompt runs about 4 points
  lower than the old one, hence the separate `legacy_*` bars in `FitConfig` for older assessments.
- The model called two roles you pursued "adjacent" (a calibration/test supervisor role and a camera/depth
  program-manager role). Worth watching: if a pattern appears, tune the domain definition, not the caps.
- Deterministic gates (strong-term evidence, title-token similarity to acted-on jobs) *lowered* recall
  (12/24 vs 16/24 at score >= 75 on the old scores) and removed none of the irrelevant jobs. Not used.
  Script: `data/scratch/calib.py`.
- On the real radar with the fit block on and the older assessments: Top picks 85, Likely fit+ 256 of 1,636 rows
  (`data/scratch/tier_count.py`). These tighten as jobs get reviewed with the new prompt.

## To do next, in this order

1. **Resume view for the reviewer.** Add `review_resume_view()` (derived copy, the file is never edited; the resume
   generator keeps the original): strip name line, email, phone, URLs, markdown emphasis and tab padding; shrink
   configurable sections (internships, student-team experience, invited talks) to one line (title, employer,
   dates). Keep summary, main roles, education, skills, publications. A `resume_compact` block in
   `config/lm_studio.yaml` lists the headings. Contact details are only ~1% of the tokens; the sections are
   ~25-30%. Then re-run `data/scratch/prompt_check.py` and check the verdicts did not move.
2. **Where the time goes (measured 2026-11-16, `qwen/qwen3.6-35b-a3b`, 3 jobs):** about 7,100-7,500 prompt tokens and
   **4,750-5,100 completion tokens** per job at 52-64 s. The JSON answer is only a few hundred tokens, so roughly
   90% of the output is the model thinking. Cutting thinking (a no-think switch, or a smaller/non-reasoning model)
   is the big speed lever; trimming the resume (about 4,500 of the 7,200 prompt tokens, and probably prefix-cached)
   is secondary. Check whether `reasoning_content` is separated by LM Studio and whether `/no_think` or a
   non-thinking model keeps the verdicts.
3. **Model bake-off (built; first overnight run started 2026-11-16 00:25).**
   - **Golden set** (`scripts/build_golden_jobs.py` -> `data/golden/golden_jobs.json`, git-ignored, back it up): 97 jobs
     snapshotted with their posting text = 34 positives (offer declined, interviewing, interviewed-rejected, applied,
     employer-rejected, saved), 60 negatives (tagged irrelevant) and 3 neutral (`okay`). Outcomes you told me that no
     table holds live in `data/golden/outcome_overrides.json`. The builder only adds, so the set cannot shrink; rerun it
     after you apply/label more jobs.
   - **Runner** (`scripts/bakeoff_models.py`): for each model on disk it `lms load`s it, runs the golden jobs through the
     real review prompt once per reasoning mode (`off` = `reasoning_effort: "none"`, `low` where the model lists it,
     `default` = the model's own setting), refreshes `report.md`/`summary.csv`/`matrix.csv` after EVERY run, then unloads
     it. Stage order (so a partial night is still useful): non-thinking models and all `off` runs first, then `low`, then
     every `default` run, smallest model first. `--run-budget-minutes` (90) caps one run, `--deadline-hours` (10) the
     night. Resumable with `--resume <dir>`; `--plan` shows the plan; `--report-only <dir>` rebuilds a report.
     It holds the shared `job-hunter` run lock (a pipeline run cannot overlap it) and unloads other models first.
     Output: `data/golden/bakeoff/<run-id>/` (`run.log` is the live progress).
   - **Models:** every LLM on disk by default (`--models a/b,c/d` to pick). The first run covered `qwen/qwen3.6-35b-a3b`
     (then the default), `qwen/qwen3.6-27b`, `qwen/qwen3.8-27b`, `qwen/qwen3-4b-2507`, `qwen/qwen3-4b` and `google/gemma-4-31b-qat`.
   - **Outcome (2026-11-16, M5 Max 128 GB):** `google/gemma-4-31b-qat` with thinking **off** is the pick: AUC 0.991, 0 of 57
     irrelevant jobs at 70 or more, 26 of 34 wanted jobs at 70 or more, about 11 s/job (the thinking run was 71 s/job and did not
     finish in budget). Runs that could not finish the golden set in 90 minutes (every thinking-on run of the 27B/35B Qwens and
     Gemma's thinking-on run) are **off the table** and marked "did not finish" in the report; the last two (qwen3.6-27b and
     qwen3.6-35b-a3b with thinking on) were stopped by hand because they could not finish. A repeat Gemma-off run was
     started to confirm. Not yet done: make the review use it (needs a `reasoning_effort` setting passed by
     `review_with_lm_studio.py`; today the config has only `model`).
   - **Publishing and reuse:** `docs/bakeoff/` holds the how-to (`README.md`) and the aggregate results (`results.csv`,
     `RESULTS.md`, no job names). `--publish <run-dir>` appends rows; each carries chip, RAM, model size, context, prompt commit,
     skill version and golden-set id so a later model can be compared on the same hardware and prompt. A test fails if a golden
     job title or key appears in a tracked file there.
   - **Reasoning switch facts (measured):** `reasoning_effort: "none"` turns thinking off on LM Studio (5 s and ~440 output
     tokens vs 54 s and ~4,950). `/no_think` in the prompt and `chat_template_kwargs.enable_thinking=false` do nothing.
     LM Studio rejects `low` on models that only list `on`/`off` (it silently falls back to `on`), so `low` is only run
     where the model lists it. No-thinking output slips on format more often (about 4 of 20 first tries), hence the one retry.
   - **How to read the report:** AUC (1.0 = every wanted job outscores every irrelevant one), `neg_ge70` (irrelevant jobs
     still reaching "Likely fit"), `pos_ge70/75/80` (wanted jobs that stay visible), `pos_off` (wanted jobs wrongly called
     off-domain), median seconds and output tokens, then `matrix.csv` with every golden job against every run.
     Decision rule: the fastest run whose AUC and `pos_ge70` match the best thinking run and whose `neg_ge70` stays near 0.
4. **Embedding experiment (ranking, not a gate).** Use LM Studio's `/v1/embeddings` (`text-embedding-qwen3-embedding-0.6b` and
   `text-embedding-nomic-embed-text-v1.5` are both served now; `qwen3-reranker-0.6b` is also present). Embed descriptions, score each job by its nearest labelled
   neighbours (acted-on positive, tagged-irrelevant negative), and compare the separation with the LLM's. If good:
   order the review queue by it (best first, every candidate still reviewed) and show a "looks like jobs you acted on"
   tag. A cross-encoder reranker (Qwen3-Reranker-0.6B) needs `transformers`/`torch`; defer until the embedding test
   shows it is worth that dependency. A 4B model for scoring is only worth it if the bake-off shows it keeps the
   separation.
5. **Re-review decision.** Older assessments have no judgments and use the stricter `legacy_*` bars. Re-reviewing the
   ~250 jobs at >= 75 with `--force` is ~3 hours at 46 s/job: decide after steps 1-3 shrink the time. The cache policy
   (key on `content_hash`, never re-review for a prompt change) stays; this would be an explicit opt-in run.
6. **Restart the live radar server** to pick up `radar.fit` (settings edits need a restart).

## Open decisions and loose ends

- Dream is still broad: the pay rule alone tags about 56% of the radar (870 of 1,539). Options: bottom of the pay range,
  a higher bar such as $200K, or leave it. (Fit tiers already ignore pay-only Dream for the Top-pick bump.)
- Record interviews/offers on the Applications page (status `interviewing`/`offer`); the history block and any
  calibration weight them most. Nothing is tagged beyond saved/applied/rejected/withdrawn yet.
- `job-hunter reevaluate-salary` (fills multi-range pay on stored jobs; local, no network) has not been run.
- Level thresholds for Honda `Career Level: N`, GM `This Level N role` and Nvidia pay-text levels are not set.
- Workday `additionalLocations` (extras will capture it from the next full run): check whether non-US primary
  locations hide US-eligible jobs. The `market` soft-exclude now also affects Ford "Marketing & Sales" engineers
  once Ford departments fill in.
- The next full pipeline run fills Ford deadlines/departments/extras and GM departments; it also scores the one job
  that the new `core integration` title term admits.
- `data/profile-diff/` holds more than your 5-report limit (generated by previews); run the report cleanup.
- `data/cleanup-exports/20261116T014618Z.json` still holds the text of a posting that cleanup deleted before the
  protection existed; restore it only if you want it back in the database.
