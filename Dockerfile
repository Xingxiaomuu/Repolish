# ── Phase 5A: Railway deployment Dockerfile ──────────────────────────
# Single image, two services:
#   Backend API: CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
#   Worker:      CMD ["python", "worker_supervisor.py"]
#
# Build:  docker build -t slidehttp .
# Run API: docker run -p 8000:8000 --env-file .env slidehttp
# Run Wkr: docker run --env-file .env slidehttp python worker_supervisor.py

FROM python:3.12-slim-bookworm

# ── System dependencies ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 18.x LTS (required by Claude Code CLI) ───────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Verify Node.js
RUN node --version && npm --version

# ── Install Claude Code CLI globally ─────────────────────────────────
# Set CI=true to skip interactive setup prompts
ENV CI=true
RUN npm install -g @anthropic-ai/claude-code 2>&1 || echo "Claude Code CLI install attempted"

# Verify claude exists (non-fatal — will be health-checked at runtime)
RUN which claude || echo "claude not on PATH yet (will be available after npm global bin setup)"
ENV PATH="/usr/local/lib/python3.12/site-packages/bin:/usr/local/bin:$PATH"

# ── Python dependencies ──────────────────────────────────────────────
WORKDIR /app/html-ppt-app/backend

COPY html-ppt-app/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --force-reinstall bcrypt==4.0.1

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

# Frontend (optional — served by backend static files if needed)
# COPY html-ppt-app/frontend/dist/ /app/html-ppt-app/frontend/dist/

# ── Create data directories ──────────────────────────────────────────
# /data is the recommended Railway volume mount point
RUN mkdir -p /data/outputs && chmod 777 /data

# ── Environment defaults ─────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV CLAUDE_CODE_COMMAND=claude
ENV CLAUDE_TIMEOUT=1800
ENV HOST=0.0.0.0
ENV PORT=8000
ENV OUTPUT_DIR=/data/outputs
ENV DATABASE_URL=sqlite:////data/app.db
ENV WORKER_COUNT=2

# ── Expose port ──────────────────────────────────────────────────────
EXPOSE 8000

# ── Default command (API service) ────────────────────────────────────
# Override for worker: CMD ["python", "worker_supervisor.py"]
WORKDIR /app/html-ppt-app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
