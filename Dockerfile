FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DATA_DIR=/data \
    DISPLAY=:99 \
    TZ=Europe/Moscow

WORKDIR /app

COPY requirements.txt .
# Both browsers have arm64 builds, so this works on a Raspberry Pi 4/5 with a 64-bit OS:
# - Camoufox (Firefox with a spoofed desktop fingerprint), downloaded from its GitHub releases;
# - Chromium for patchright.
# Plus Xvfb: a headed browser on a virtual screen gets through the DNS anti-bot more often.
RUN pip install --no-cache-dir -r requirements.txt \
    && patchright install --with-deps chromium \
    && playwright install-deps firefox \
    && python -m camoufox fetch \
    && apt-get update \
    && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=1m --timeout=10s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/status', timeout=5)"

ENTRYPOINT ["docker-entrypoint.sh"]
