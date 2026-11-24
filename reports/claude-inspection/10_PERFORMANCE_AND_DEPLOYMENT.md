# 10 — Performance and Deployment

## Measured in this inspection
- **Model inference:** real, see report 06 and `evidence/claude-inspection/benchmarks/model_inference_benchmark.json`.

| Model | Cold start (TTFT) | Warm TTFT | Throughput |
|---|---|---|---|
| 4B | 15.2 s | 0.67–0.74 s | ~65 tok/s |
| 9B | 27.6 s | not measured | ~38 tok/s |

- **Memory:** host RAM peaked at ~15.9 GB of 16 GB, with Docker, browser and Ollama running together.
- **Platform load and DR:** not re-run. Those scripts write to the shared database; the previous figures are classified **NOT VERIFIED** here.

## Performance risks found in code
- `OllamaProvider.generate` is `async` but uses blocking `urllib.request.urlopen` (`ollama_provider.py:76`). A single cold generation blocks every other request in the process for up to the timeout.
- RAG similarity is an O(n) Python loop over every chunk in the tenant.
- Process-local lock dictionaries grow without bound.
- With a 5 s provider timeout and a 15–28 s measured cold start, the first AI request after idle returns fabricated text (F-16).

## Deployment readiness
| Item | Observed |
|---|---|
| Compose | PostgreSQL 16, Redis 7, MinIO (pinned tag). 127.0.0.1 binds, healthchecks, limits, `no-new-privileges`. **No API, worker, identity, Temporal, OTel, reverse proxy or Ollama service.** |
| Dependency manifest | **None** (no requirements/pyproject/lock). `.env.example` references `asyncpg`, which is not installed. |
| Health/readiness | `/health` static; `/ready` hardcoded "UP" for DB/Redis/storage (`main.py:96-98`). |
| Migrations at startup | Not run. `init_db` is imported but never called; init-db.sql only runs on first container creation. |
| Secrets | Defaults in code and compose (F-10); no secret injection. |
| TLS | None. |
| CI/CD | No workflow files. |
| Backup/restore | AES-GCM backup script exists. The DR drill used and committed a plaintext dump (F-22). |
| Logging/monitoring | Python logging + in-app telemetry tables; no exporter or alerting pipeline. |
| Rollback | Runbook prose only; no versioned artifacts or images. |
| Clean-environment reproducibility | **Not reproducible.** No manifest; the app needs a hand-built `.env`. The template's superuser connection is the only way login works. |

## Readiness ladder
| Level | Verdict |
|---|---|
| Local development | **Yes, with effort** (Python 3.14 environment assembled by hand, Docker, Ollama). |
| Academic demonstration | **Yes, conditionally.** Show the domain core through tests/API and the UI through a static server. Disclose that voice, tools, payments and carriers are simulated. Do not demo with real data. |
| MVP | No (no auth UI, no wired screens, P0s). |
| Pilot customer | No. |
| Production | No. |
| Enterprise SaaS | No. |
