# 09 — Test Quality and Evidence

## Execution (this inspection)
- **Command:** `python -m pytest tests -p no:cacheprovider -rA --durations=25 --junitxml=…`, with `PYTHONDONTWRITEBYTECODE=1`.
- **Environment:** Python 3.14.6, pytest 9.1.1, PostgreSQL 16.15 container up, Ollama up (the agent tests made real 4B calls).
- **Result:** **381 collected, 381 passed, exit 0, 326.44 s** (wall time 5 m 58 s).
- **Logs:**
  - `evidence/claude-inspection/test-logs/full_suite_run2.log`
  - `full_suite_run2_junit.xml`
  - An earlier run with PostgreSQL down produced failures and errors: `run1_full_suite_pg_down.log`.
- **Conclusion on reproducibility:** the suite depends on a live, pre-initialised shared database and on Ollama. It is not hermetic.

## Pre-run safety and side effects
- **Safety precautions:**
  - Before running, I took a `pg_dump` to the scratchpad and recorded per-table row counts (`evidence/claude-inspection/db/rowcounts_before.csv`).
  - The database held only synthetic tenants left by earlier test runs.
- **Side effects found:**
  - The suite **added** rows to 20 tables (+2 tenants, +2 users, +2 quotes, …), see `rowcount_diff_after_tests.txt`. No pre-existing rows were removed (counts only increased).
  - The suite **overwrote a tracked evidence file**: `evidence/step-10/multilingual_voice_evaluation.json`, field `evaluation_duration_ms`. I restored it with `git checkout`.

## Integrity problems
| Problem | Example | Effect |
|---|---|---|
| Tests encode insecure behaviour as success | `tests/voice/test_voice_api_contract.py:96` verifies a caller with `otp_code: "123456"`; line 203 confirms step-up with `"123456"`; `tests/voice/test_manager_copilot_and_mfa.py:110` uses `"654321"` | The backdoors are protected by the suite. |
| Tautological assertion | `tests/integration/test_postgres_rls.py` asserts the policy count is in `(6, 12, 13, 25, 36, 56, 59, 64, 67, 71, 79)`. The list grew in 10 commits (`4c7ea5d` … `6f09998`). | Cannot detect a missing policy. |
| Widened acceptance | `test_multilingual_voice_end_to_end.py` changed `== 60` to `in (60, 90)` (`6f09998`). Harmless correction. | — |
| Platform skip widened | `test_step03_real_postgres.py`: `if sys.platform == "win32"` → `… and sys.version_info < (3, 14)` (`fd06ff7`) | Compatibility fix; acceptable. |
| E2E tests do not exercise the product boundary | Scenarios A–E use in-memory SQLite and call services directly. No HTTP, no auth, no RLS, no UI. | "E2E" overstates coverage. |
| Missing negative tests | No test for unauthenticated `X-Tenant-ID`, forged payment webhook with a wrong secret source, cumulative refunds, wrong TOTP, foreign action token, guard with no evidence | All P0s in this report pass the suite. |
| Mocks presented as integrations | Carrier, payment, telephony and n8n tests verify adapters and simulators | Fine as unit tests, but reported as "verified integrations". |
| Evaluations validate their own fixtures | `src/ai/evaluations/*` check rule code on author-written inputs | Not model evaluations. |
| Frontend tests | None (no Playwright/Jest) | UI breakage (CSP) undetected. |

## What the tests do prove (credit)
- Money arithmetic.
- Quote / approval / order state machines.
- Concurrency at service level, including real-PostgreSQL tests for hot SKUs and approval races.
- Channel webhook signatures and deduplication.
- Out-of-order messages.
- Outbox leasing.
- RLS read isolation for the app role.
- Conversation ownership and takeover.
- G.711 codec and VAD.

## Previous evidence claims — reliability
| Claim | Reliability |
|---|---|
| "381/381 passing" | **Reproduced.** |
| Voice 518/569 ms "measured" | **Not reliable** (constants). |
| 14,398 req/s safe read | Not re-run; measures an in-process path. Treat as unverified. |
| DR RTO 1.35 s | Restore of a small dev DB; plausible but not production-representative. The dump is committed unencrypted (F-22). |
| 82/82 controls verified | **Contradicted.** |
| LID 90 %, injection 100 % | Rule checks on a self-authored text set. |
