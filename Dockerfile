# syntax=docker/dockerfile:1

# Keep the direct-build default in sync with docker-compose.yml.
ARG GIGASTT_TAG=2.22.0
FROM ghcr.io/ekhodzitsky/gigastt:${GIGASTT_TAG} AS engine
FROM ghcr.io/ggml-org/whisper.cpp@sha256:317bebdff53d7bd9414ff1c1214101764eaa426e16e06468d08c9fee18c9cb8e AS whisper

# Keep the official Caddy binary; refresh Alpine security packages.
FROM caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0 AS caddy
RUN apk upgrade --no-cache

# The engine needs trixie's libstdc++; security fixes can postdate the base image.
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 AS runtime-base
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends python3 ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Keep pip and build-time wheels out of the runtime image.
FROM runtime-base AS dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-venv \
    && python3 -m venv "$VIRTUAL_ENV"
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip uninstall -y pip

FROM node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530 AS web-build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM runtime-base AS app-base
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=engine /usr/local/bin/gigastt /usr/local/bin/gigastt

WORKDIR /app

ENV MODEL_DIR=/models \
    DATA_DIR=/data \
    ENGINE_BIN=/usr/local/bin/gigastt \
    CONSOLE_PORT=8080 \
    PYTHONPATH=/app/backend
RUN mkdir -p /models /data
VOLUME ["/models", "/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["python", "-m", "uvicorn", "console.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8080", "--no-access-log", \
     "--timeout-graceful-shutdown", "15"]

FROM runtime-base AS parakeet
ARG PARAKEET_COMMIT=01abde80dd018570f7590bf59fcb46a495e8c0c2
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*
RUN git init /src && git -C /src fetch --depth=1 https://github.com/mudler/parakeet.cpp.git "${PARAKEET_COMMIT}" \
    && git -C /src checkout --detach FETCH_HEAD \
    && git -C /src submodule update --init --depth 1 third_party/ggml \
    && cmake -S /src -B /build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
         -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DGGML_NATIVE=OFF -DPARAKEET_SHARED=ON \
         -DPARAKEET_BUILD_CLI=OFF -DPARAKEET_BUILD_SERVER=OFF -DPARAKEET_WITH_CED=OFF \
         -DPARAKEET_WITH_VOICEDETECT=OFF \
    && cmake --build /build --target parakeet -j 4

FROM dependencies AS multiengine-dependencies
RUN python -m ensurepip \
    && python -m pip install --no-cache-dir sherpa-onnx==2.0.3 onnxruntime==1.32.0 tokenizers==0.23.3 numpy==2.5.5 \
    && python -m pip uninstall -y pip

FROM app-base AS multiengine
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=whisper /app/build/bin/whisper-server /app/build/bin/whisper-server
COPY --from=whisper /app/build/bin/libwhisper.so* /app/build/bin/
COPY --from=whisper /app/build/bin/libggml*.so* /app/build/bin/
COPY --from=parakeet /build/libparakeet.so /opt/parakeet/libparakeet.so
COPY --from=multiengine-dependencies /opt/venv /opt/venv
ENV WHISPER_BIN=/app/build/bin/whisper-server PARAKEET_LIB=/opt/parakeet/libparakeet.so
COPY backend/ /app/backend/
COPY --from=web-build /web/dist/ /app/frontend/dist/

FROM dependencies AS gigaam-v4-dependencies
COPY requirements-gigaam-v4.txt /tmp/requirements-gigaam-v4.txt
RUN cp -a /opt/venv /opt/gigaam-v4 \
    && /opt/gigaam-v4/bin/python -m ensurepip \
    && /opt/gigaam-v4/bin/python -m pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
         -r /tmp/requirements-gigaam-v4.txt \
    && /opt/gigaam-v4/bin/python -m pip uninstall -y pip

FROM multiengine AS gigaam-v4
COPY --from=gigaam-v4-dependencies /opt/gigaam-v4 /opt/gigaam-v4
ENV GIGAAM_V4_PYTHON=/opt/gigaam-v4/bin/python

FROM app-base AS app
COPY backend/ /app/backend/
COPY --from=web-build /web/dist/ /app/frontend/dist/

FROM app AS standard
