FROM python:3.11-slim-bookworm AS builder

# Build arguments for Lance version
ARG LANCEDB_VERSION=0.29.2

WORKDIR /build

COPY backend/requirements.txt backend/constraints-${LANCEDB_VERSION}.txt ./
RUN pip install --no-cache-dir --user -c constraints-${LANCEDB_VERSION}.txt \
    -r requirements.txt

FROM python:3.11-slim-bookworm

RUN groupadd -r appuser && useradd -r -g appuser -u 1001 appuser

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /home/appuser/.local

WORKDIR /app

COPY backend/*.py .
COPY docker/entrypoint.sh /app/entrypoint.sh
COPY web/vanilla/ /web/

RUN chmod +x /app/entrypoint.sh
RUN chown -R appuser:appuser /app /web
RUN chmod -R 755 /web

USER appuser

ENV PATH=/home/appuser/.local/bin:$PATH
ENV DATA_PATH=/data
ENV PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/healthz || exit 1

# Build arguments for labels (redeclare after FROM)
ARG LANCEDB_VERSION=0.29.2

LABEL org.opencontainers.image.title="Lance Data Viewer"
LABEL org.opencontainers.image.description="Read-only web viewer for Lance datasets"
LABEL org.opencontainers.image.source="https://github.com/gordonmurray/lance-data-viewer"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.licenses="MIT"
LABEL com.github.lancedb.version="${LANCEDB_VERSION}"

ENTRYPOINT ["/app/entrypoint.sh"]
