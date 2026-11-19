# Planted-bug benchmark

Split: **dev** · 8 pull requests (6 with a planted bug, 2 clean). A comment is a hit if it is within 2 lines of a planted bug.

| | Linters only (ruff + bandit) | LLM reviewer | LLM + verifier (posted) |
|---|---|---|---|
| Bugs caught | **3 / 6** (50%) | **6 / 6** (100%) | **6 / 6** (100%) |
| High-severity bugs caught | 67% | 100% | 100% |
| Comments that point at a real bug | 75% of 4 | 80% of 10 | 80% of 10 |
| False alarms (comments) | 1 | 2 | 2 |
| Clean PRs with any comment | 1 / 2 | 2 / 2 | 2 / 2 |
| Security bugs caught | 2 / 2 | 2 / 2 | 2 / 2 |
| Correctness bugs caught | 0 / 2 | 2 / 2 | 2 / 2 |
| Performance bugs caught | 0 / 1 | 1 / 1 | 1 / 1 |
| Reliability bugs caught | 1 / 1 | 1 / 1 | 1 / 1 |

LLM cost: $0.0053 in total, $0.00066 per PR · 15,904 tokens · LLM time per PR p50 2.3 s (includes waits for free-tier rate limits).

| Case | Planted bug | Linters | LLM | LLM + verifier | False alarms (posted) |
|---|---|---|---|---|---|
| `clean-rename-docstring` | clean PR | ✅ | ⚠️ 1 | ⚠️ 1 | billing/invoice.py:3 KeyError on missing dict fields |
| `clean-parameterised-sql` | clean PR | ⚠️ 1 | ⚠️ 1 | ⚠️ 1 | billing/queries.py:19 Indentation error causes SyntaxError |
| `cor-pagination-off-by-one` | slice end drops the last item of every page | ❌ | ✅ | ✅ |  |
| `cor-inverted-discount` | condition inverted: small orders ship free, large ones pay | ❌ | ✅ | ✅ |  |
| `perf-n-plus-one` | one database query per order (N+1) | ❌ | ✅ | ✅ |  |
| `rel-no-timeout` | HTTP call without a timeout can hang the worker forever | ✅ | ✅ | ✅ |  |
| `sec-sql-search` | SQL built with an f-string from request input | ✅ | ✅ | ✅ |  |
| `sec-yaml-load` | yaml.load with the full loader on an uploaded file | ✅ | ✅ | ✅ |  |
