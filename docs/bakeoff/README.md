# Choosing a local review model (the bake-off)

The review stage scores every candidate with a local LM Studio model. Which model, and whether its
"thinking" is on, changes both **quality** (does it keep the jobs you want and drop the ones you don't?)
and **time** (seconds per job, so hours per run). This folder holds a tool to measure that on *your*
hardware with *your* history, and the results we measured so far.

- `results.csv`: one row per (run, model, thinking mode). Aggregates only.
- `RESULTS.md`: the same rows as tables, grouped by hardware. Generated; do not edit by hand.

## What the results say (and don't)

Read the tables in `RESULTS.md`, then these limits:

- **One candidate's data.** The numbers come from one person's golden set (automotive ADAS and validation).
  They show how the models behave, not that your ranking will be identical. Run it on your own history.
- **Small sample.** About 100 jobs, a third of them positives. AUC gaps of a few hundredths are within noise.
  Repeat a run before relying on a close call.
- **Tied to the prompt.** Every row records the review-prompt commit and `job-reviewer` skill version. A different
  prompt can reorder the models; compare rows only when `prompt_commit` and `golden_id` match.
- **Time is a requirement.** A run has a time budget (default 90 minutes). A model/mode that cannot score the whole
  golden set inside it is listed as **did-not-finish**, with no quality numbers, and is excluded: too slow for this
  workflow means off the table, and a partial sample is not comparable with a complete one.

## Findings so far (2026-11-16, Apple M5 Max 128 GB, review prompt `8515779`)

- **`google/gemma-4-31b-qat` with thinking off is the pick.** Two runs agree (AUC 0.992 and 0.991, none of the 57 irrelevant
  jobs at 70 or more, 25-26 of 34 wanted jobs at 70 or more, about 11 s/job, 19 GB). Its thinking-on run needed 71 s/job and did not
  finish in budget.
- **Thinking off is the lever on every model that has the switch:** about 10x faster, and on the Qwen 27B/35B models the only
  way to finish at all. Every thinking-on run of those models is did-not-finish.
- **The current default (`qwen3.6-35b-a3b`, off) is fast (4 s/job) but keeps only 14 of 34 wanted jobs at 70 or more.**
- **Small and MoE models separate the domains poorly:** `qwen3-4b` lets 31-41 of 60 irrelevant jobs reach 70 or more;
  `nemotron-3-nano-omni` (off) never scored above 79, passed 22 of 55 irrelevant jobs at 70 or more and failed the JSON schema
  on 8 of 97 jobs. `qwen3-4b-2507` is clean on noise (0 of 55) but its AUC is 0.91.
- **Resume view** (`resume_view` in `config/lm_studio.yaml`): the condensed, contact-free resume (internships, student-team and
  invited-talks sections cut to one line) was neutral on speed (10.5 vs about 11 s/job, the prompt prefix is cached) and slightly worse
  on recall: 22 of 33 wanted jobs at 70 or more against 25-26 of 34, AUC 0.987 against 0.991-0.992. Stripping only the contact block
  and URLs cannot change a verdict and saves tokens and privacy, so that is what to enable; leave `compact_sections` empty unless your
  own bake-off says otherwise. The published row marked `resume view: on` is the condensed variant.
- **Seniority ceiling removed (job-reviewer 1.4.0):** a level mismatch used to cap a score at 74. With no ceiling and a prompt that treats a lead role in the core domain as a match, Gemma (off) scored AUC 1.000, 0 of 60 irrelevant jobs at 70 or more and 24 of 34 wanted at 70 or more, with 97 of 97 valid answers. Recall did not improve (25-26 of 34 before): the missed jobs score 58-68 because the model itself lists missing people-management or organisation-wide scope as gaps, not because of the ceiling. The row's prompt commit reads `271c680-dirty` (the change was committed after the run).
- Thinking-on runs that did not finish are listed in `RESULTS.md` without quality numbers.

## Run it on your machine

You need a golden set: the jobs you acted on or labelled, with their posting text.

```bash
uv run python scripts/build_golden_jobs.py          # needs >= 8 wanted jobs and >= 8 tagged irrelevant
uv run python scripts/bakeoff_models.py --plan      # which models and thinking modes it would run
caffeinate -i uv run python scripts/bakeoff_models.py     # (macOS) all LLMs in LM Studio; or --models a/b,c/d
```

- It loads each model with `lms`, runs the golden jobs through the real review prompt once per thinking mode the
  model supports (`off`, `low`, `default`), and unloads it. Nothing touches your database, assessments or radar.
- Output is in `data/golden/bakeoff/<run-id>/`: `report.md` (refreshed after every run), `summary.csv`,
  `matrix.csv` (per-job scores) and `meta.json` (hardware, prompt commit, golden set id). All of it is git-ignored.
  The per-job files name your real jobs and outcomes: **never commit them**.
- `--models` takes LM Studio keys (see `lms ls`) or `all` (default). Embedding and OCR models in the list will simply
  fail to produce a verdict, so name the models you actually want to compare.
- Off macOS the GPU is not auto-detected: pass `--hardware-note "RTX 4090 24GB"` so the result says what it ran on.
- Useful limits: `--run-budget-minutes` (90), `--deadline-hours` (10), `--limit N` (a balanced smoke test),
  `--modes off,default`, `--resume <dir>`, `--report-only <dir>`.

## How to read the columns

| column | meaning | want |
|---|---|---|
| AUC | chance that a job you wanted outscores one you tagged irrelevant | high (1.0 perfect, 0.5 chance) |
| irrelevant ≥70 | irrelevant jobs that would still reach "Likely fit" | 0 |
| wanted ≥70 / ≥75 / ≥80 | wanted jobs that stay visible at that score | high |
| wanted called off-domain | wanted jobs the model called off your domain (these would be capped at 49) | 0 |
| secs/job, total min | speed on that hardware | low |

Pick the fastest complete run whose AUC is near the best, with irrelevant ≥70 near 0 and most wanted jobs kept.
Then set the model in `config/lm_studio.yaml`.

## Share or compare a result

```bash
uv run python scripts/bakeoff_models.py --publish data/golden/bakeoff/<run-id> [more run dirs]
```

This appends aggregate rows to `results.csv` and rebuilds `RESULTS.md`. It writes no company, title, job id or
per-job score, and refuses if the golden set changed after the run. `tests/test_bakeoff_models.py` fails if a
golden job's title or key ever appears in a tracked file here. Rows are append-only; a published row is never rewritten.

## Testing a newer model later

1. Download it in LM Studio and check `lms ls`.
2. Run the bake-off with the model **and the current default** (`--models new/model,current/default`), so both are scored
   on today's golden set and prompt. Do not compare against old rows when `golden_id` or `prompt_commit` differ.
3. Publish the run. If the new model is complete, faster or better on the columns above, switch.
