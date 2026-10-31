FROM node:22-bookworm-slim AS ui

WORKDIR /ui
RUN npm install -g pnpm@11.28.3
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend ./
RUN pnpm build


FROM nvidia/cuda:13.3.0-runtime-ubuntu24.04

ENV PYTHONUNBUFFERED=1 \
    ELYSIAN_HOME=/data/elysian \
    ELYSIAN_RUNTIME_BACKEND=sglang \
    ELYSIAN_SGLANG_BASE_URL=http://127.0.0.1:8000/v1 \
    ELYSIAN_UI_DIR=/srv/elysian/ui

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3.12 python3.12-venv python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend ./backend
COPY README.md ./

RUN python3.12 -m venv /opt/elysian \
    && /opt/elysian/bin/pip install --upgrade pip setuptools wheel \
    && /opt/elysian/bin/pip install ./backend

COPY --from=ui /ui/dist /srv/elysian/ui

EXPOSE 8765
CMD ["/opt/elysian/bin/elysian", "serve", "--host", "0.0.0.0", "--port", "8765"]
