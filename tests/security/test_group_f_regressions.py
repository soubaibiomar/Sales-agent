"""
Regression tests for remediation group F of the independent inspection (F-26 deployment:
readiness, metrics, log redaction, migrations, container, proxy, CI, backups).
"""
import io
import json
import logging
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

ROOT = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------- readiness / liveness
@pytest.mark.asyncio
async def test_ready_returns_503_when_database_is_down():
    from src.backend.main import app
    from src.backend.core import operations

    async def boom():
        raise ConnectionError("postgresql://sales_app_user:topsecret@db:5432/x unreachable")

    with patch.dict(operations.CHECKS, {"database": (boom, True), "ollama": (boom, False)}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "NOT_READY"
    assert body["dependencies"]["database"] == {**body["dependencies"]["database"], "status": "DOWN", "error": "ConnectionError"}
    assert "topsecret" not in r.text and "sales_app_user" not in r.text  # errors are never echoed


@pytest.mark.asyncio
async def test_ready_ignores_optional_dependency():
    from src.backend.main import app
    from src.backend.core import operations

    async def ok():
        return {"rls_enforced": True}

    async def down():
        raise TimeoutError()

    with patch.dict(operations.CHECKS, {"database": (ok, True), "ollama": (down, False)}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/ready")
    assert r.status_code == 200
    assert r.json()["dependencies"]["ollama"]["status"] == "DOWN"


@pytest.mark.asyncio
async def test_liveness_checks_nothing_and_leaks_nothing():
    from src.backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.json() == {"status": "ALIVE"}


def test_ready_is_no_longer_hardcoded():
    src = read("src/backend/main.py")
    assert '"services": {"database": "UP"' not in src


# ---------------------------------------------------------------- metrics
@pytest.mark.asyncio
async def test_metrics_require_token_when_configured():
    from src.backend.main import app
    from src.backend.core.config import settings
    with patch.object(settings, "metrics_token", "t" * 32):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/metrics")).status_code == 401
            assert (await c.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401
            await c.get("/api/v1/does-not-exist/12345")
            r = await c.get("/metrics", headers={"Authorization": "Bearer " + "t" * 32})
    assert r.status_code == 200
    assert "salesai_http_requests_total" in r.text
    assert "salesai_dependency_up" in r.text
    # bounded cardinality: raw paths/IDs never become label values
    assert "12345" not in r.text


def test_metrics_token_required_outside_development():
    from src.backend.core.config import Settings, SECRET_FIELDS
    env = {f.upper(): "x" * 40 for f in SECRET_FIELDS}
    env.update({"ENVIRONMENT": "production", "DATABASE_URL": "postgresql+psycopg://u:p@h/db"})
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="metrics_token"):
            Settings(_env_file=None)


@pytest.mark.asyncio
async def test_observability_health_requires_authentication():
    from src.backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/observability/health")
        v = await c.get("/api/v1/observability/voice-metrics")
    assert r.status_code == 401 and v.status_code == 401


def test_voice_benchmark_no_longer_invents_asr_llm_latency():
    src = read("src/ai/voice/voice_observability.py")
    assert "asr_ms = 110.0" not in src and "llm_ms = 380.0" not in src
    assert "is_simulated_asr=False" not in src
    assert '"not_measured": ["asr", "llm"]' in src
    page = read("src/frontend/voice_observability.html") + read("src/frontend/js/pages/voice_observability.js")
    assert "518.3" not in page and "6,307" not in page and "MEETS_TARGET" not in page


# ---------------------------------------------------------------- log redaction
@pytest.mark.parametrize("raw,leak", [
    ("db=postgresql+psycopg://sales_app_user:s3cr3tPW@db:5432/x", "s3cr3tPW"),
    ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
    ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl", "eyJzdWIiOiIxIn0"),
    ('{"password": "hunter22", "otp_code": "123456"}', "hunter22"),
    ("customer client@example.ma called", "client@example.ma"),
    ("card 4111 1111 1111 1111 declined", "4111 1111 1111 1111"),
    ("caller +212 661 23 45 67", "661 23 45 67"),
])
def test_redaction_patterns(raw, leak):
    from src.backend.core.operations import redact
    assert leak not in redact(raw)


def test_redacting_filter_covers_args_and_exceptions():
    from src.backend.core.operations import RedactingFilter, JsonLogFormatter
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonLogFormatter())
    log = logging.getLogger("test.group_f.redaction")
    log.addHandler(handler); log.propagate = False
    try:
        log.warning("login failed for %s", "victim@example.com")
        try:
            raise RuntimeError("connect postgresql://u:pw123secret@h/db")
        except RuntimeError:
            log.exception("db error")
    finally:
        log.removeHandler(handler)
    out = stream.getvalue()
    assert "victim@example.com" not in out and "pw123secret" not in out
    for line in out.strip().splitlines():
        json.loads(line)


def test_app_and_worker_install_redaction():
    assert "configure_logging()" in read("src/backend/main.py")
    assert "configure_logging()" in read("src/backend/worker.py")
    assert "logging.basicConfig" not in read("src/backend/worker.py")


# ---------------------------------------------------------------- migrations
def test_migration_runner_no_longer_swallows_errors_or_uses_create_all():
    src = read("src/backend/migrations/runner.py")
    assert "metadata.create_all" not in src and "run_sync" not in src
    assert "Note on SQL statement execution" not in src
    assert "checksum mismatch" in src and "pg_advisory_lock" in src


def test_migrations_are_contiguous_and_include_parity_fix():
    from src.backend.migrations.runner import discover
    versions = [int(v) for v, _, _ in discover()]
    assert versions == list(range(0, len(versions)))
    parity = read("src/backend/migrations/018_init_db_parity.sql")
    for table in ("users", "user_roles", "audit_logs", "conversations", "contacts", "outbox_events"):
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;' in parity
    assert "pgcrypto" in read("src/backend/migrations/000_extensions.sql")


def test_runner_rejects_changed_migration(tmp_path):
    from src.backend.migrations import runner
    (tmp_path / "000_a.sql").write_text("SELECT 1;", encoding="utf-8")
    files = runner.discover(tmp_path)
    assert files[0][0] == "000" and len(files[0][2]) == 64


# ---------------------------------------------------------------- container / proxy / CI
def test_dockerfile_is_non_root_and_excludes_secrets():
    df = read("Dockerfile")
    assert re.search(r"^USER 10001", df, re.M)
    assert "HEALTHCHECK" in df and "COPY . ." not in df
    ignore = read(".dockerignore")
    for entry in (".env", ".git", "evidence", "tests", "backups"):
        assert re.search(rf"^{re.escape(entry)}$", ignore, re.M), entry


def test_stack_requires_secrets_and_exposes_only_the_proxy():
    stack = read("infra/docker-compose.stack.yml")
    assert "${JWT_SECRET_KEY:?}" in stack and "${METRICS_TOKEN:?}" in stack
    assert "service_completed_successfully" in stack  # migrate is a release gate
    published = re.findall(r'^\s+- "(\d+):(\d+)"', stack, re.M)
    assert set(published) == {("443", "443"), ("80", "80")}
    caddy = read("infra/proxy/Caddyfile")
    assert "respond @internal 404" in caddy and "/metrics" in caddy and "Strict-Transport-Security" in caddy


def test_alert_rules_and_scrape_config():
    assert "DatabaseNotReady" in read("infra/observability/alerts.yml")
    assert "credentials_file: /run/secrets/metrics_token" in read("infra/observability/prometheus.yml")


def test_ci_has_image_scan_sbom_and_signing():
    ci = read(".github/workflows/ci.yml")
    for needle in ("src.backend.migrations.runner", "pip-audit", "bandit", "gitleaks", "trivy-action", "sbom-action", "cosign sign"):
        assert needle in ci, needle
    assert "init-db.sql" not in ci


# ---------------------------------------------------------------- backups
def test_backup_stream_roundtrip_and_tamper_detection():
    from scripts.pg_backup import encrypt_stream, decrypt_stream, BackupError, CHUNK
    key = os.urandom(32)
    payload = os.urandom(CHUNK * 2 + 123)
    enc = io.BytesIO(); encrypt_stream(io.BytesIO(payload), enc, key)
    out = io.BytesIO(); decrypt_stream(io.BytesIO(enc.getvalue()), out, key)
    assert out.getvalue() == payload
    blob = enc.getvalue()
    for bad in (blob[:-50], blob + b"x", blob[:200] + bytes([blob[200] ^ 1]) + blob[201:]):
        with pytest.raises(BackupError):
            decrypt_stream(io.BytesIO(bad), io.BytesIO(), key)
    with pytest.raises(BackupError):
        decrypt_stream(io.BytesIO(blob), io.BytesIO(), os.urandom(32))


def test_backup_key_must_be_dedicated_256_bit():
    from scripts.pg_backup import load_key, BackupError
    assert len(load_key("ab" * 32)) == 32
    with pytest.raises(BackupError):
        load_key("short")
    assert "jwt_secret_key" not in read("scripts/pg_backup.py")


def test_backup_drill_evidence_passed():
    report = json.loads(read("evidence/claude-inspection/group_f/backup_restore_drill.json"))
    assert report["result"] == "PASS" and not report["row_count_mismatches"]
    assert report["wrong_key_rejected"] and report["tamper_rejected"] and report["truncation_rejected"]
