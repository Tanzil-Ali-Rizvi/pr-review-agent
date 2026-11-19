# Planted-bug benchmark

Split: **test** · 35 pull requests (27 with a planted bug, 8 clean). A comment is a hit if it is within 2 lines of a planted bug and names the problem (keyword match), so a different complaint about the same line does not count.

| | Linters only (ruff + bandit) | LLM reviewer | LLM + verifier (posted) |
|---|---|---|---|
| Bugs caught | **12 / 27** (44%) | **25 / 27** (93%) | **24 / 27** (89%) |
| High-severity bugs caught | 57% | 100% | 100% |
| Comments that point at a real bug | 87% of 15 | 65% of 40 | 69% of 36 |
| False alarms (comments) | 2 | 14 | 11 |
| Clean PRs with any comment | 1 / 8 | 5 / 8 | 4 / 8 |
| Security bugs caught | 7 / 9 | 9 / 9 | 9 / 9 |
| Correctness bugs caught | 4 / 10 | 10 / 10 | 9 / 10 |
| Performance bugs caught | 0 / 4 | 2 / 4 | 2 / 4 |
| Reliability bugs caught | 1 / 4 | 4 / 4 | 4 / 4 |

LLM cost: $0.0231 in total, $0.00066 per PR · 74,070 tokens · LLM time per PR p50 7.9 s (includes waits for free-tier rate limits).

| Case | Planted bug | Linters | LLM | LLM + verifier | False alarms (posted) |
|---|---|---|---|---|---|
| `clean-type-hints-helper` | clean PR | ✅ | ✅ | ✅ |  |
| `clean-subprocess-list` | clean PR | ⚠️ 1 | ⚠️ 1 | ⚠️ 1 | ops/backup.py:13 Untrusted executable path |
| `clean-logging-comprehension` | clean PR | ✅ | ⚠️ 1 | ✅ |  |
| `clean-add-tests` | clean PR | ✅ | ✅ | ✅ |  |
| `clean-timeout-raise` | clean PR | ✅ | ⚠️ 1 | ⚠️ 1 | geo/lookup.py:10 Silent None return may cause downstream crashes |
| `clean-lru-cache` | clean PR | ✅ | ✅ | ✅ |  |
| `clean-env-config` | clean PR | ✅ | ⚠️ 2 | ⚠️ 2 | app/settings.py:9 Invalid PAGE_SIZE causes crash; app/settings.py:10 Missing DATABASE_URL crashes import |
| `clean-dataclass-refactor` | clean PR | ✅ | ⚠️ 3 | ⚠️ 2 | billing/lines.py:12 Negative quantity now raises error; billing/lines.py:14 Discount validation too strict |
| `cor-mutable-default` | mutable default list shared across calls | ✅ | ✅ | ✅ |  |
| `cor-is-literal` | string compared with 'is' instead of == | ✅ | ✅ | ✅ |  |
| `cor-floor-average` | floor division truncates the average rating | ❌ | ✅ | ✅ |  |
| `cor-naive-local-time` | compares local time with a UTC timestamp | ❌ | ✅ | ❌ |  |
| `cor-late-binding` | lambdas capture the loop variable, so every handler uses the last event name | ✅ | ✅ | ✅ |  |
| `cor-remove-while-iterating` | removing from a list while iterating over it skips items | ❌ | ✅ | ✅ |  |
| `cor-default-now` | datetime.now() evaluated once at import time as a default | ✅ | ✅ | ✅ |  |
| `cor-percent-change` | percentage change divides by the new value instead of the old one | ❌ | ✅ | ✅ |  |
| `cor-missing-branch` | returns None for other tiers, so the price calculation raises TypeError | ❌ | ✅ | ✅ |  |
| `cor-top-n-order` | sorts ascending, so it returns the three lowest sellers | ❌ | ✅ | ✅ |  |
| `perf-list-membership` | membership test on a growing list makes dedup quadratic | ❌ | ❌ | ❌ | newsletter/importer.py:10 Inefficient duplicate detection |
| `perf-config-in-loop` | re-reads and parses the JSON file for every transaction | ❌ | ✅ | ✅ |  |
| `perf-load-whole-table` | loads the whole events table and filters in Python | ❌ | ✅ | ✅ |  |
| `perf-sequential-awaits` | awaits independent HTTP calls one after another instead of concurrently | ❌ | ❌ | ❌ | quotes/suppliers.py:15 Unhandled exception from price_from |
| `rel-swallowed-payment-error` | exception swallowed, then the order is marked paid anyway | ✅ | ✅ | ✅ |  |
| `rel-unclosed-files` | opens thousands of files without closing them | ❌ | ✅ | ✅ |  |
| `rel-missing-await` | coroutine is never awaited, so the notification is never sent | ❌ | ✅ | ✅ | notify/shipping.py:1 Signature change breaks existing callers |
| `rel-hot-retry-loop` | retries forever with no delay or limit, hammering the API and hanging the job | ❌ | ✅ | ✅ |  |
| `sec-shell-thumbnail` | uploaded filename interpolated into a shell command | ✅ | ✅ | ✅ |  |
| `sec-hardcoded-key` | live API secret committed in source | ✅ | ✅ | ✅ |  |
| `sec-pickle-cookie` | unpickling data from a client-controlled cookie | ✅ | ✅ | ✅ | shop/cart.py:15 pickle used for cookie serialization |
| `sec-path-traversal` | user-supplied file name joined to a base dir without checking it stays inside | ❌ | ✅ | ✅ |  |
| `sec-md5-passwords` | passwords stored as unsalted MD5 | ✅ | ✅ | ✅ |  |
| `sec-verify-false` | TLS certificate checks disabled for a financial API | ✅ | ✅ | ✅ | settlements/fetch.py:21 Assumes 'items' key always present |
| `sec-weak-reset-token` | reset token generated with the non-cryptographic random module | ✅ | ✅ | ✅ |  |
| `sec-eval-calculator` | eval on a user-entered formula | ✅ | ✅ | ✅ |  |
| `sec-admin-bypass-injection` | permission check skipped for any user whose name starts with 'svc-' | ❌ | ✅ | ✅ |  |
