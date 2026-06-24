# ============================================================
# Dockerfile — Enterprise Decision Intelligence Platform
# ============================================================
# Build:  docker build -t decision-intelligence .
# Run:    docker run -p 8501:8501 --env-file .env decision-intelligence
# ============================================================

FROM python:3.11-slim AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# ── Dependencies (cached layer) ──────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Application source ───────────────────────────────────────────────────────
COPY --chown=appuser:appuser . .

# Create runtime directories
RUN mkdir -p storage logs reports \
    && chown -R appuser:appuser /app

# ── Switch to non-root ───────────────────────────────────────────────────────
USER appuser

# Initialise DB schema at build time
RUN python -c "from storage.database import Database; Database()"

# ── Runtime ──────────────────────────────────────────────────────────────────
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["streamlit", "run", "streamlit_app.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0", \
            "--server.headless=true"]
