# syntax=docker/dockerfile:1.7

FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS web-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM --platform=$TARGETPLATFORM python:3.13-slim-bookworm AS python-deps
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SPOTDL_CONFIG_ROOT=/config \
    SPOTDL_MUSIC_DIR=/music

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-deps /usr/local /usr/local
COPY . /app
COPY --from=web-build /app/web/dist /app/web/dist

RUN rm -rf /app/.venv /app/web/node_modules /app/web/dist/assets/.vite /app/downloads /app/credentials.json

EXPOSE 5555
VOLUME ["/config", "/music"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,urllib.request;print(json.loads(urllib.request.urlopen('http://127.0.0.1:5555/healthz',timeout=3).read().decode()).get('status')=='ok')" | grep -q True

CMD ["python", "main.py"]
