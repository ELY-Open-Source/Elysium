FROM node:22-bookworm-slim AS ui

WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build


FROM nvidia/cuda:13.3.0-runtime-ubuntu24.04

ENV PYTHONUNBUFFERED=1 \
    ELYSIUM_HOME=/data/elysium \
    ELYSIUM_RUNTIME_BACKEND=sglang \
    ELYSIUM_SGLANG_BASE_URL=http://127.0.0.1:8000/v1 \
    ELYSIUM_UI_DIR=/srv/elysium/ui

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3.12 python3.12-venv python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend ./backend
COPY README.md ./

RUN python3.12 -m venv /opt/elysium \
    && /opt/elysium/bin/pip install --upgrade pip setuptools wheel \
    && /opt/elysium/bin/pip install ./backend

COPY --from=ui /ui/dist /srv/elysium/ui

EXPOSE 8765
CMD ["/opt/elysium/bin/elysium", "serve", "--host", "0.0.0.0", "--port", "8765"]
