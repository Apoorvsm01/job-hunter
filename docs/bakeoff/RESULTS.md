# Local-model bake-off results

Generated from `results.csv` by `scripts/bakeoff_models.py --publish`; do not edit by hand. Aggregates only: no company, title or
job appears here. See [README.md](README.md) for how to read, run and reproduce this, and for the caveats.

## Apple M5 Max, 128 GB

Run 2026-11-16, review prompt `8515779` (job-reviewer 1.3.0), context 32768, golden set `814fe2f222` (97 jobs: 34 wanted, 60 tagged irrelevant).

| run | model | size GB | thinking | resume view | AUC | irrelevant ≥70 | wanted ≥70 | wanted ≥75 | wanted ≥80 | wanted called off-domain | secs/job (median) | total min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-16-T-07-45-gemma-confirm | google/gemma-4-31b-qat | 18.9 | off | off | 0.992 | 0/57 | 25/34 | 18/34 | 16/34 | 1/34 | 11.8 | 19.7 |
| 2026-11-16-T-00-25-35 | google/gemma-4-31b-qat | 18.9 | off | off | 0.991 | 0/57 | 26/34 | 18/34 | 17/34 | 1/34 | 10.9 | 19.0 |
| 2026-11-16-T-00-25-35 | qwen/qwen3.6-27b | 29.5 | off | off | 0.972 | 0/60 | 20/34 | 16/34 | 10/34 | 7/34 | 20.5 | 34.4 |
| 2026-11-16-T-00-25-35 | qwen/qwen3.6-35b-a3b | 37.7 | off | off | 0.965 | 0/56 | 14/34 | 14/34 | 4/34 | 5/34 | 4.2 | 7.2 |
| 2026-11-16-T-00-25-35 | qwen/qwen3.8-27b | 29.5 | off | off | 0.952 | 0/60 | 13/34 | 11/34 | 8/34 | 5/34 | 21.2 | 35.1 |
| 2026-11-16-T-00-25-35 | qwen/qwen3-4b-2507 | 4.3 | default | off | 0.912 | 0/55 | 28/34 | 17/34 | 16/34 | 6/34 | 3.5 | 6.2 |
| 2026-11-16-T-00-25-35 | qwen/qwen3-4b | 4.3 | default | off | 0.857 | 31/60 | 28/34 | 25/34 | 24/34 | 1/34 | 11.4 | 19.7 |
| 2026-11-16-T-08-nemotron-off | nvidia/nemotron-3-nano-omni | 26.1 | off | off | 0.779 | 22/55 | 30/32 | 28/32 | 0/32 | 2/32 | 3.4 | 6.0 |
| 2026-11-16-T-00-25-35 | qwen/qwen3-4b | 4.3 | off | off | 0.757 | 41/60 | 30/34 | 28/34 | 26/34 | 4/34 | 2.4 | 3.9 |

**Did not finish inside the time budget: excluded, no quality numbers (a partial sample is not comparable).**

| run | model | thinking | jobs done | secs/job (median) |
|---|---|---|---|---|
| 2026-11-16-T-00-25-35 | google/gemma-4-31b-qat | default | 76/97 | 71.1 |
| 2026-11-16-T-00-25-35 | qwen/qwen3.6-27b | default | 11/97 | 205.6 |
| 2026-11-16-T-00-25-35 | qwen/qwen3.8-27b | default | 26/97 | 203.6 |
| 2026-11-16-T-00-25-35 | qwen/qwen3.8-27b | low | 51/97 | 90.8 |

## Apple M5 Max, 128 GB

Run 2026-11-16, review prompt `9412a2f-dirty` (job-reviewer 1.3.0), context 32768, golden set `814fe2f222` (97 jobs: 34 wanted, 60 tagged irrelevant).

| run | model | size GB | thinking | resume view | AUC | irrelevant ≥70 | wanted ≥70 | wanted ≥75 | wanted ≥80 | wanted called off-domain | secs/job (median) | total min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-16-T-09-resume-view | google/gemma-4-31b-qat | 18.9 | off | on | 0.987 | 0/60 | 22/33 | 18/33 | 16/33 | 2/33 | 10.5 | 18.1 |

