# One image for the API and the Celery workers: same code, different command.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --create-home --uid 10001 jamii
WORKDIR /app

COPY api/pyproject.toml api/pyproject.toml
COPY api/src api/src
COPY workers/pyproject.toml workers/pyproject.toml
COPY workers/src workers/src
RUN pip install ./api ./workers

COPY api/alembic api/alembic
COPY api/alembic.ini api/alembic.ini

USER jamii
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1
# Migrations run as a separate one-off step (see infra/scripts/deploy.sh), never on API start.
CMD ["uvicorn", "jamii_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", \
     "--forwarded-allow-ips", "*", "--workers", "2"]
