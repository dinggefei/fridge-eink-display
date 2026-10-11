FROM python:3.12-slim

ARG UV_VERSION=0.11.3
ARG PYPI_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PIP_INDEX_URL="${PYPI_INDEX_URL}" \
    UV_DEFAULT_INDEX="${PYPI_INDEX_URL}" \
    PATH="/app/.venv/bin:${PATH}"

RUN sed -i \
        -e 's|http://deb.debian.org/debian|https://mirrors.cloud.tencent.com/debian|g' \
        -e 's|http://deb.debian.org/debian-security|https://mirrors.cloud.tencent.com/debian-security|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-zenhei fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "uv==${UV_VERSION}" \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv lock --default-index "${PYPI_INDEX_URL}" \
    && uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY THIRD_PARTY_NOTICES.md ./
COPY app ./app
COPY migrations ./migrations
COPY tools ./tools

RUN mkdir -p /app/data/recognition \
    && chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
