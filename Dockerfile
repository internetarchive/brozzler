FROM ghcr.io/astral-sh/uv:python3.12-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends chromium

ENV BROZZLER_EXTRA_CHROME_ARGS=--no-sandbox

WORKDIR /app

COPY . .

RUN uv sync --frozen --all-extras --no-dev
