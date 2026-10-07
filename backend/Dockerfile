# StegoLab API
#   docker build -t stegolab-api ./backend                                   # CPU PyTorch (portable)
#   docker build -t stegolab-api --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128 ./backend
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend

COPY requirements.txt .
RUN pip install torch torchvision --index-url ${TORCH_INDEX} \
    && pip install -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY pipeline ./pipeline
# Trained model artefacts (weights + metrics). Mounted as a volume in docker-compose for updates.
COPY models ./models
COPY demo_carriers ./demo_carriers

RUN useradd --create-home --uid 10001 stegolab \
    && mkdir -p /srv/backend/storage \
    && chown -R stegolab:stegolab /srv/backend
USER stegolab

ENV APP_ENV=production \
    MODEL_PATH=/srv/backend/models \
    UPLOAD_DIR=/srv/backend/storage \
    DATASET_DIR=/srv/data/dataset

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Single worker: the rate limiter and the loaded model live in-process (see docs/DEPLOYMENT.md).
CMD ["sh", "-c", "alembic upgrade head && (python -m app.cli bootstrap-admin || true) && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
