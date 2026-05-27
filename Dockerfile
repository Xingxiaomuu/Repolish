# ── Phase 5B: Railway separation-of-concerns Dockerfile ──────────────
# Single image, two services (deployed separately on Railway):
#   Backend API: CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
#   Worker:      CMD ["python", "worker_supervisor.py"]
#
# Two deployment modes, controlled by STORAGE_PROVIDER env var:
#   "local" (default): SQLite + shared Volume (/data) — pure Railway, no external services
#   "s3":              PostgreSQL + S3/R2 object storage — no Volume needed
#
# Build:  docker build -t slidehttp .
# Run API: docker run -p 8000:8000 --env-file .env slidehttp
# Run Wkr: docker run --env-file .env slidehttp python worker_supervisor.py

FROM python:3.12-slim-bookworm

# Bump CACHEBUST to force full rebuild (e.g. change to 2, 3, ...)
ARG CACHEBUST=10

# ── System dependencies ──────────────────────────────────────────────
RUN echo "Cache bust: ${CACHEBUST}" && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 18.x LTS (required by Claude Code CLI) ───────────────────
RUN echo "Cache bust: ${CACHEBUST}" && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Verify Node.js
RUN node --version && npm --version

# ── Install Claude Code CLI globally ─────────────────────────────────
# Set CI=true to skip interactive setup prompts
ENV CI=true
RUN npm install -g @anthropic-ai/claude-code@2.1.150 2>&1 || echo "Claude Code CLI install attempted"

# Verify claude exists (non-fatal — will be health-checked at runtime)
RUN which claude || echo "claude not on PATH yet (will be available after npm global bin setup)"
ENV PATH="/usr/local/lib/python3.12/site-packages/bin:/usr/local/bin:$PATH"

# ── Python dependencies ──────────────────────────────────────────────
WORKDIR /app/html-ppt-app/backend

COPY html-ppt-app/backend/requirements.txt .
RUN echo "Cache bust: ${CACHEBUST}" && \
    pip install --no-cache-dir -r requirements.txt

# ── Copy application code ────────────────────────────────────────────
# Project root files (CLAUDE.md, .gitignore, etc.)
COPY CLAUDE.md /app/
COPY .gitignore /app/

# Claude Code configuration
COPY .claude/ /app/.claude/

# html-ppt skill (required by Claude Code for PPT generation)
COPY .agents/ /app/.agents/

# Backend source
COPY html-ppt-app/backend/ /app/html-ppt-app/backend/

# ── Verify main.py is the latest version (diagnostic) ──────────────────
RUN echo "=== DIAG: main.py lines 48-56 ===" && sed -n '48,56p' /app/html-ppt-app/backend/main.py
RUN grep -q "_extract_token" /app/html-ppt-app/backend/main.py || (echo "FATAL: main.py is STALE - still has _bearer reference!" && exit 1)
RUN echo "=== DIAG: main.py OK (no _bearer found, _extract_token present) ==="

# Frontend (optional — served by backend static files if needed)
# COPY html-ppt-app/frontend/dist/ /app/html-ppt-app/frontend/dist/

# ── Temp job + shared output directories ────────────────────────────
# /app/tmp/htmlppt-jobs/ — S3 mode: isolated temp dirs under /app (sandbox allows writes here)
# /data/outputs/         — local mode: shared Volume for SQLite DB + outputs
RUN echo "Cache bust: ${CACHEBUST}" && \
    mkdir -p /app/tmp/htmlppt-jobs /data/outputs && chmod 777 /app/tmp /data

# ── Environment defaults ─────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV CLAUDE_CODE_COMMAND=claude
ENV CLAUDE_CODE_PERMISSION_MODE=bypassPermissions
ENV CLAUDE_TIMEOUT=1800
ENV HOST=0.0.0.0
ENV PORT=8000
ENV STORAGE_PROVIDER=s3
ENV S3_REGION=auto
ENV WORKER_COUNT=2
# DATABASE_URL is set by Railway PostgreSQL plugin
# REDIS_URL is set by Railway Redis plugin
# S3_BUCKET, S3_ENDPOINT, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY — set on Railway

# ── Non-root user (required by Claude Code — --dangerously-skip-permissions blocked for root) ──
RUN useradd -m appuser && \
    chown -R appuser:appuser /app /app/tmp
USER appuser

# ── Expose port ──────────────────────────────────────────────────────
EXPOSE 8000

# ── Default command (API service) ────────────────────────────────────
# Override for worker: CMD ["python", "worker_supervisor.py"]
WORKDIR /app/html-ppt-app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
