# The model service: the only container where AI runs. CPU-only by default.
FROM python:3.12-slim

ARG EXTRAS=""
# The registry, trained models and held-out test ids live on a volume, so promotions survive redeploys.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JAMII_ML_REGISTRY=/srv/ml/registry.yaml
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10002 jamii
WORKDIR /app

COPY ml/service/pyproject.toml ml/service/pyproject.toml
COPY ml/service/src ml/service/src
# EXTRAS=whisper (speech-to-text) and/or ner, once a model for them is approved.
RUN pip install "./ml/service${EXTRAS:+[$EXTRAS]}"
COPY ml/scripts ml/scripts
COPY ml/registry.yaml ml/registry.yaml

RUN mkdir -p /srv/ml && chown jamii /srv/ml
USER jamii
EXPOSE 8100
# First start on an empty volume: seed it with the repository's registry (keyword baseline only).
CMD ["sh", "-c", "[ -f \"$JAMII_ML_REGISTRY\" ] || cp /app/ml/registry.yaml \"$JAMII_ML_REGISTRY\"; exec uvicorn jamii_ml.app:app --host 0.0.0.0 --port 8100"]
