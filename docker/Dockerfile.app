ARG NODE_IMAGE=node:24-bookworm-slim
ARG PYTHON_IMAGE=python:3.11-slim-bookworm
FROM ${NODE_IMAGE} AS web
WORKDIR /build/webui
COPY webui/package.json webui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY webui/ ./
RUN npm run build

FROM ${PYTHON_IMAGE}
ARG APP_UID=1000
ARG APP_GID=1000
ARG BUILD_PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG BUILD_DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never UV_NO_SYNC=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright PATH=/opt/venv/bin:$PATH
COPY --from=web /usr/local/bin/node /usr/local/bin/node
RUN pip install --no-cache-dir --timeout 120 --index-url ${BUILD_PIP_INDEX} uv==0.11.0
WORKDIR /app
RUN sed -i "s|http://deb.debian.org/debian|${BUILD_DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg libgl1 ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /root/.cache/uv
COPY . ./
COPY --from=web /build/api/webui ./api/webui
RUN groupadd --gid ${APP_GID} app \
    && useradd --uid ${APP_UID} --gid ${APP_GID} --create-home app \
    && mkdir -p /app/data /app/logs /app/browser_data \
    && chown app:app /app/data /app/logs /app/browser_data
USER app
RUN PYTHONPATH=/app MEDIACRAWLER_CONTAINER_MODE=1 MEDIACRAWLER_IMAGE_PROVIDER=siliconflow \
    MEDIACRAWLER_BROWSER_CHANNEL=chromium python docker/check_runtime.py
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
