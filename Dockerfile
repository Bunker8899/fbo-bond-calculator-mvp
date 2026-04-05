# ══════════════════════════════════════════════════════════════════════════════
# Stage 1 – Builder
# Compiles wheels so the runtime stage needs no compiler toolchain.
# ══════════════════════════════════════════════════════════════════════════════
FROM python:3.11-slim AS builder

WORKDIR /build

# gcc is required for some native extensions (e.g. orjson, aiohttp)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip --no-cache-dir \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# ══════════════════════════════════════════════════════════════════════════════
# Stage 2 – Runtime  (lean, no build tools, non-root)
# ══════════════════════════════════════════════════════════════════════════════
FROM python:3.11-slim AS runtime

# ── Python env flags ──────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN addgroup --system --gid 1001 appgroup \
    && adduser  --system --uid 1001 --gid 1001 --no-create-home appuser

WORKDIR /app

# ── Install pre-built wheels (no network, no compiler required) ───────────────
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt

# ── Application files ─────────────────────────────────────────────────────────
COPY --chown=appuser:appgroup main.py bonds_data.json ./

# ── Drop privileges ───────────────────────────────────────────────────────────
USER appuser

# ── Network ───────────────────────────────────────────────────────────────────
EXPOSE 8080

# ── Liveness probe ────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8080/_nicegui/3.9.0/static/favicon.ico')" \
    || exit 1

# ── Entrypoint ────────────────────────────────────────────────────────────────
CMD ["python", "main.py"]
