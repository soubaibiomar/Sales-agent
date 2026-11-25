"""
Production operations primitives (inspection finding F-26, controls 42-43, 46).

* Readiness   - real dependency checks with timeouts; /ready returns 503 when the
                database (the only hard dependency) is unreachable or bypasses RLS.
* Metrics     - Prometheus exposition with bounded-cardinality labels (route *template*,
                never the raw path), served at /metrics behind an operator token.
* Log hygiene - a logging filter that redacts credentials and personal data from every
                record (message, arguments and exception text) before any handler sees it.

Previously /ready answered {"database": "UP", ...} without checking anything, health
latencies were hardcoded, and the "PII-redacting" JSON formatter redacted nothing.
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import text

from src.backend.core.config import settings

# --------------------------------------------------------------------------------------
# Log redaction
# --------------------------------------------------------------------------------------
_REDACTIONS = [
    # Credentials embedded in connection URLs: scheme://user:secret@host
    (re.compile(r"(?P<p>\b[a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+(?=@)", re.I), r"\g<p>[REDACTED]"),
    # Bearer / JWT tokens
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I), "Bearer [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "[REDACTED_JWT]"),
    # key=value / "key": "value" secrets
    (re.compile(r"(?P<k>\b(?:password|passwd|pwd|secret|token|api[_-]?key|authorization|otp|otp_code|mfa_code|totp_code)\b[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&}]+", re.I),
     r"\g<k>[REDACTED]"),
    # E-mail addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    # Payment card numbers (13-19 digits, optional separators)
    (re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), "[REDACTED_NUMBER]"),
    # Phone numbers in international format (+212..., +33...)
    (re.compile(r"\+\d[\d .-]{7,15}\d"), "[REDACTED_PHONE]"),
]


def redact(value: str) -> str:
    for pattern, repl in _REDACTIONS:
        value = pattern.sub(repl, value)
    return value


class RedactingFilter(logging.Filter):
    """Rewrites each record so no handler or formatter can emit secrets or PII."""

    @staticmethod
    def _clean(value):
        return redact(value) if isinstance(value, str) else value

    def filter(self, record: logging.LogRecord) -> bool:
        # Keep the record's shape: some formatters (uvicorn's access log) unpack record.args,
        # so arguments are redacted one by one instead of being merged into the message.
        record.msg = redact(str(record.msg)) if isinstance(record.msg, str) else record.msg
        if isinstance(record.args, tuple):
            record.args = tuple(self._clean(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: self._clean(v) for k, v in record.args.items()}
        try:  # verify the final message is still clean (e.g. secrets split across arguments)
            message = record.getMessage()
            if redact(message) != message and not isinstance(record.args, tuple):
                record.msg, record.args = redact(message), None
        except Exception:  # malformed %-args: fall back to the redacted raw template
            record.msg, record.args = redact(str(record.msg)), None
        if record.exc_info:
            # Pre-render the traceback so exception messages are redacted too.
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_text:
            payload["exception"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False)


_configured = False


def configure_logging(json_logs: Optional[bool] = None) -> None:
    """Install redaction on the root logger (idempotent). JSON lines outside development."""
    global _configured
    root = logging.getLogger()
    if json_logs is None:
        json_logs = not settings.is_development
    if not _configured:
        root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
        if not root.handlers:
            root.addHandler(logging.StreamHandler())
        _configured = True
    for handler in root.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
        if json_logs:
            handler.setFormatter(JsonLogFormatter())
    # uvicorn installs its own handlers on these loggers; protect them as well.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactingFilter) for f in handler.filters):
                handler.addFilter(RedactingFilter())


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------
REGISTRY = CollectorRegistry(auto_describe=True)
HTTP_REQUESTS = Counter(
    "salesai_http_requests_total", "HTTP requests by route template and status class",
    ["method", "route", "status"], registry=REGISTRY,
)
HTTP_LATENCY = Histogram(
    "salesai_http_request_duration_seconds", "HTTP request latency by route template",
    ["method", "route"], registry=REGISTRY,
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
DEPENDENCY_UP = Gauge(
    "salesai_dependency_up", "1 when the last readiness check of a dependency succeeded",
    ["dependency"], registry=REGISTRY,
)
DEPENDENCY_LATENCY = Gauge(
    "salesai_dependency_check_seconds", "Duration of the last readiness check per dependency",
    ["dependency"], registry=REGISTRY,
)


class MetricsMiddleware:
    """Pure ASGI middleware (does not buffer bodies; safe for WebSockets and streaming)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", None) or ("/app/*" if scope.get("path", "").startswith("/app") else "unmatched")
            method = scope.get("method", "GET")
            HTTP_REQUESTS.labels(method, template, f"{status_holder['code'] // 100}xx").inc()
            HTTP_LATENCY.labels(method, template).observe(time.perf_counter() - start)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


# --------------------------------------------------------------------------------------
# Readiness
# --------------------------------------------------------------------------------------
async def _check_database() -> Dict[str, Any]:
    from src.backend.core.database import engine, assert_rls_enforced_connection
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    warning = await assert_rls_enforced_connection()
    if warning and not settings.is_development:
        raise RuntimeError("connection bypasses row-level security")
    return {"rls_enforced": warning is None}


async def _check_ollama() -> Dict[str, Any]:
    from src.ai.config import ai_config
    async with httpx.AsyncClient(timeout=2.0) as client:
        r = await client.get(ai_config.ollama_base_url.rstrip("/") + "/api/tags")
        r.raise_for_status()
    return {}


# Only the database gates readiness: without it nothing works. The model runtime is
# reported but optional - AI turns already fail closed (no evidence -> no claims).
CHECKS = {"database": (_check_database, True), "ollama": (_check_ollama, False)}


async def readiness(timeout: float = 3.0) -> Dict[str, Any]:
    async def run(name, fn):
        start = time.perf_counter()
        # asyncio.wait_for() waits for the cancelled check to *finish* cancelling. Against a
        # frozen database (paused container, network partition) cancelling a query on a
        # pooled connection can itself hang, so /ready stalled past its budget (observed
        # in the stack run). Give up at the deadline and let the task cancel in background.
        task = asyncio.ensure_future(fn())
        try:
            done, _ = await asyncio.wait({task}, timeout=timeout)
            if not done:
                task.cancel()
                task.add_done_callback(lambda t: t.cancelled() or t.exception())  # silence late errors
                raise TimeoutError()
            details = task.result()
            ok, error = True, None
        except Exception as exc:  # never leak connection strings or hostnames
            details, ok, error = {}, False, type(exc).__name__
        elapsed = time.perf_counter() - start
        DEPENDENCY_UP.labels(name).set(1 if ok else 0)
        DEPENDENCY_LATENCY.labels(name).set(elapsed)
        result = {"status": "UP" if ok else "DOWN", "latency_ms": round(elapsed * 1000, 1), **details}
        if error:
            result["error"] = error
        return name, result

    results = dict(await asyncio.gather(*(run(n, fn) for n, (fn, _) in CHECKS.items())))
    ready = all(results[n]["status"] == "UP" for n, (_, required) in CHECKS.items() if required)
    return {
        "status": "READY" if ready else "NOT_READY",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "dependencies": {n: {**r, "required": CHECKS[n][1]} for n, r in results.items()},
    }
