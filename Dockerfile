# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile for Fashion Commerce Backend
#
# Stages:
#   1. builder  — install dependencies into a venv, nothing extra in the image
#   2. runtime  — copy only the venv + application code; no build tools
#
# Why multi-stage?
# - The builder stage can install gcc / build headers needed for some packages.
# - The runtime image never contains pip, setuptools, or build tools — smaller
#   attack surface and smaller image size.
# - Typical size reduction: ~50% vs single-stage.
# ─────────────────────────────────────────────────────────────────────────────


# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Prevent .pyc files and force stdout/stderr to be unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Create a virtual environment inside the build stage.
# We copy it to the runtime stage — no pip needed at runtime.
RUN python -m venv /build/.venv

# Copy only requirements first (Docker layer cache: if requirements.txt
# doesn't change, this expensive step is skipped on subsequent builds).
COPY requirements.txt .

# Install dependencies into the venv.
# --no-cache-dir reduces layer size.
RUN /build/.venv/bin/pip install --no-cache-dir --upgrade pip && \
    /build/.venv/bin/pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Point Python at the venv copied from the builder
    PATH="/app/.venv/bin:$PATH" \
    VIRTUAL_ENV="/app/.venv"

# Create a non-root user for security.
# Running as root inside a container is a security anti-pattern.
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy the built venv from the builder stage
COPY --from=builder /build/.venv /app/.venv

# Copy the application source code
COPY --chown=appuser:appgroup . .

# Switch to non-root user
USER appuser

# Expose the API port
EXPOSE 8000

# Health check — polls /health every 30s.
# The app has 40s to start (index creation, MongoDB ping).
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Use exec form (not shell form) so signals are forwarded correctly.
# --workers 1: single worker (single MongoDB connection pool, safe for asyncio).
# --loop uvloop: faster event loop (installed via uvicorn[standard]).
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--loop", "uvloop"]
