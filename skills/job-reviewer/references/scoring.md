# Candidate scoring

This rubric is embedded verbatim into the prompt `scripts/review_with_lm_studio.py` sends to the
local model for each job, one at a time — it is not applied by the coordinating agent itself (see
`SKILL.md`'s procedure). Score one job against the resume, from 0 to 100:

- Core domain and technical relevance: 30
- Experience and seniority alignment: 20
- Skills, tools, and methods overlap: 20
- Responsibility and ownership alignment: 15
- Career progression and role quality: 10
- Other profile preferences: 5

Bands: 90–100 exceptional, 80–89 strong, 75–79 good, below 75 omit by default.
Location carries no quality points after U.S. eligibility. Penalize missing required qualifications materially and missing preferred qualifications modestly. If the resume does not establish a qualification, describe it as “not evidenced.”

Cite two to four concrete matches and one to three meaningful gaps using both job-description and resume/profile evidence. Do not score by raw keyword count. Before the number, record three judgments: `domain_fit` (core / adjacent / off, judged by the technology area the role works on, not its job function), `seniority_fit` (below / match / above) and `blockers` (hard requirements clearly unmet; empty if none). The script then caps the score deterministically: off-domain 49, adjacent 74, any blocker 69, seniority other than match 74; every cap is written into the gaps with the model's own number. Fewer than about 1 in 10 postings deserve 80 or more; when unsure between two bands, take the lower.

Respond with only the JSON object the prompt specifies (domain_fit, seniority_fit, blockers, matches, gaps, score, recommended — in that order) — nothing else.

