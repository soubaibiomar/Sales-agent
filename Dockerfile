# Sales AI Management Platform - API / worker / migration image (inspection finding F-26).
# One image, three roles chosen by the command:
#   api      uvicorn src.backend.main:app            (default CMD)
#   worker   python -m src.backend.worker
#   migrate  python -m src.backend.migrations.runner (release step, owner credentials)
#
# Pin the base by digest in your registry mirror for reproducible, signed builds:
#   docker buildx imagetools inspect python:3.14-slim-bookworm
ARG PYTHON_IMAGE=python:3.14-slim-bookworm

# ---- build stage: compile wheels into an isolated virtualenv --------------------------
FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt /tmp/requirements.txt
RUN pip install --require-virtualenv -r /tmp/requirements.txt

# ---- runtime stage: no compilers, no pip cache, non-root ------------------------------
FROM ${PYTHON_IMAGE} AS runtime
LABEL org.opencontainers.image.title="sales-ai-platform" \
      org.opencontainers.image.source="https://github.com/soubaibiomar/Sales-agent"
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    PIPER_VOICES_DIR=/models/piper-voices \
    HF_HOME=/models/huggingface
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /srv --shell /usr/sbin/nologin app \
 && mkdir -p /models /srv && chown app:app /models
COPY --from=build /opt/venv /opt/venv
WORKDIR /srv
# Only what the processes need: no tests, evidence, reports or local data.
COPY --chown=app:app src ./src
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "src.backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
