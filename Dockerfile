FROM ghcr.io/astral-sh/uv:python3.12-bookworm

ARG CHROME_CHANNEL=stable
ARG TARGETARCH
ARG CHROME_DEB_URL=https://dl.google.com/linux/direct/google-chrome-${CHROME_CHANNEL}_current_${TARGETARCH}.deb
ADD ${CHROME_DEB_URL} /tmp/chrome.deb
RUN apt-get update && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm -rf /tmp/chrome.deb /var/lib/apt/lists/* \
    && google-chrome-${CHROME_CHANNEL} --version
COPY chrome-policies.json /etc/opt/chrome/policies/managed/brozzler.json

ENV BROZZLER_EXTRA_CHROME_ARGS=--no-sandbox

WORKDIR /app

COPY . .

RUN uv sync --frozen --all-extras --no-dev
