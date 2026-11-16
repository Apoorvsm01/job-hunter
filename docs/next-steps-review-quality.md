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
2. **Measure where the 46 s goes.** Send one job and read `usage.prompt_tokens` vs `completion_tokens`. If it is
   mostly thinking tokens, turn thinking off for this JSON task (Qwen: `chat_template_kwargs`/`/no_think`, or
   gpt-oss low reasoning effort) before trimming anything else. The resume sits at the start of every request, so
   LM Studio's prefix cache may already hide its cost.
3. **Model bake-off on the same 38 jobs.** Candidates on the server: `qwen/qwen3.6-35b-a3b` (current),
   `qwen/qwen3.6-27b`, `qwen/qwen3.8-27b`; optionally a downloaded gpt-oss-20b, Gemma 3 27B or a Qwen 4B.
   Judge by: separation (acted-on vs irrelevant), valid-JSON rate, seconds per job, cap behaviour. Skip the
   `deepseek-r1` distill and the "uncensored/heretic" variants. Do not fine-tune yet (63 labels, one resume).
4. **Embedding experiment (ranking, not a gate).** Use LM Studio's `/v1/embeddings` (`text-embedding-nomic-embed-text-v1.5`
   is loaded; a Qwen3-Embedding-0.6B GGUF is an option). Embed descriptions, score each job by its nearest labelled
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
