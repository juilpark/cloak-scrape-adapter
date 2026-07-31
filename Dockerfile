FROM python:3.12-slim

ARG SOURCE_URL=https://github.com/juilpark/cloak-scrape-adapter
ARG REVISION=unknown
ARG VERSION=dev

LABEL org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=3000 \
    CLOAKBROWSER_CACHE_DIR=/home/app/.cloakbrowser \
    CLOAKBROWSER_AUTO_UPDATE=false \
    PYTHONPATH=/app/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        fonts-freefont-ttf \
        fonts-ipafont-gothic \
        fonts-liberation \
        fonts-noto-color-emoji \
        fonts-tlwg-loma-otf \
        fonts-unifont \
        fonts-wqy-zenhei \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libatspi2.0-0 \
        libcairo-gobject2 \
        libcairo2 \
        libcups2 \
        libdbus-1-3 \
        libdrm2 \
        libfontconfig1 \
        libgbm1 \
        libgdk-pixbuf-2.0-0 \
        libglib2.0-0 \
        libgtk-3-0 \
        libnspr4 \
        libnss3 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libx11-6 \
        libx11-xcb1 \
        libxcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
        libxshmfence1 \
        libxss1 \
        libxtst6 \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --home-dir /home/app app \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.lock LICENSE THIRD_PARTY_NOTICES.md ./

# Installs the MIT-licensed wrapper only. Do not launch CloakBrowser here:
# launch would download a separately licensed Chromium binary into the image.
RUN python -m pip install \
        --no-cache-dir \
        --require-hashes \
        --requirement requirements.lock \
    && mkdir -p /home/app/.cloakbrowser \
    && chown -R app:app /home/app

COPY src/ src/

USER app

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '3000') + '/health', timeout=8)"

CMD ["sh", "-c", "exec uvicorn cloak_scrape_adapter.app:app --host 0.0.0.0 --port \"${PORT}\" --workers 1"]
