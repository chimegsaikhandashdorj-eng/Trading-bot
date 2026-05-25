# syntax=docker/dockerfile:1.7
# Multi-stage Dockerfile for the trading bot.
# MetaTrader5 and TA-Lib are Windows-only / require system libs — install them
# at the deployment site if running on those targets. This image is for the
# Binance+Telegram subset (Linux-compatible).

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Strip MT5 + TA-Lib from requirements (Linux-incompatible) for this image.
COPY requirements.txt .
RUN grep -v -E '^(MetaTrader5|TA-Lib)' requirements.txt > requirements-linux.txt && \
    pip install --user -r requirements-linux.txt


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/root/.local/bin:$PATH

WORKDIR /app

# Install runtime tools (curl for healthcheck, tini as init)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl tini && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY . .

# Persist logs and SQLite outside the image layer
VOLUME ["/app/logs", "/app/data"]

# Health server port
EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Bind health server to all interfaces inside the container
ENV HEALTH_HOST=0.0.0.0

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "main.py"]
