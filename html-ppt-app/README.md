# HTML PPT Generator

A local web app that generates static HTML presentations using Claude Code + html-ppt-skill.
Phase 4A: async task queue with Redis + RQ + SQLite.

## Architecture

```
Frontend (Vite + React + TypeScript)
  → POST /api/jobs → returns job_id immediately
    → Backend (Python FastAPI)
      → Enqueues RQ job in Redis
        → Worker (RQ worker process)
          → subprocess → Claude Code CLI
            → html-ppt-skill
              → index.html → standalone.html → zip
    ← Frontend polls GET /api/jobs/{job_id} every 2s
```

## Prerequisites

- Python 3.10+
- Node.js 18+
- Redis (for the task queue)
- Claude Code CLI installed and authenticated
- html-ppt-skill installed

## Install html-ppt-skill

```bash
npx skills add https://github.com/lewislulu/html-ppt-skill
```

## Install Redis

**Windows**: Download from https://github.com/tporadowski/redis/releases or use WSL.

**macOS**: `brew install redis`

**Linux**: `sudo apt install redis-server`

## Install & Run

### Terminal 1 — Redis

```bash
redis-server
```

### Terminal 2 — Backend (API server)

```bash
cd backend

# Create virtual environment (recommended)
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start API server (--host 0.0.0.0 allows LAN access)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 3 — Worker

```bash
cd backend

# Activate the same venv
venv\Scripts\activate

# Start RQ worker
python worker.py
```

### Terminal 4 — Frontend

```bash
cd frontend

# Install dependencies (first time only)
npm install

# Start dev server (--host 0.0.0.0 allows LAN access)
npm run dev -- --host 0.0.0.0
```

The frontend runs at `http://localhost:5173` and proxies API requests to the backend at `http://localhost:8000`.

## LAN Access

With `--host 0.0.0.0`, other devices on the same LAN can access:
- Frontend: `http://<your-ip>:5173`
- Backend API: `http://<your-ip>:8000`

**Phone via hotspot**: If your phone shares a hotspot and your computer connects to it, both devices are on the same LAN. Use your computer's hotspot IP (check with `ipconfig` on Windows → Wireless LAN adapter IPv4 Address). A phone connected to the same hotspot can access `http://<computer-ip>:5173`.

## Configure Claude Code CLI

```bash
# Windows PowerShell
$env:CLAUDE_CODE_COMMAND = "claude"
$env:CLAUDE_TIMEOUT = "1800"
```

## Admin Dashboard

An admin dashboard is available at `http://localhost:5173/admin`. It provides:
- System summary (total jobs, success rate, avg generation time, estimated token usage)
- Queue status (Redis connection, worker count, RQ queue length)
- Job table with status filter and pagination
- Per-job detail view with timing, token estimates, quality reports
- Settings management (worker count)

### Admin Password

Set `ADMIN_PASSWORD` in `backend/.env` to protect the admin dashboard:

```env
ADMIN_PASSWORD=your-secret-password
```

If not set, the admin dashboard is open without authentication (local use only).

Access the admin API with header `X-Admin-Password: <password>`.

### Worker Count

Configure the desired worker count:

```env
# In backend/.env
WORKER_COUNT=2

# Or via admin UI (saved to database)
# Admin Dashboard → Settings → Worker Count → Save
```

**Important**: Changing `desired_worker_count` via the admin UI only updates the database setting. Restart `worker_supervisor.py` for the change to take effect.

The command-line argument `--count` takes priority:
```bash
python worker_supervisor.py --count 3   # Ignore WORKER_COUNT env / DB setting
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | / | Health check |
| POST | /api/jobs | Create a generation job (returns immediately) |
| GET | /api/jobs/{job_id} | Get job status and results |
| GET | /api/jobs | List recent jobs |
| GET | /api/download/{job_id}/html | Download index.html |
| GET | /api/download/{job_id}/standalone | Download standalone.html |
| GET | /api/download/{job_id}/zip | Download ZIP bundle |
| GET | /api/admin/summary | (Auth) System aggregate statistics |
| GET | /api/admin/jobs | (Auth) Paginated job list with filters |
| GET | /api/admin/jobs/{job_id} | (Auth) Full job detail + quality report |
| GET | /api/admin/queue | (Auth) Redis/RQ queue status |
| GET | /api/admin/settings | (Auth) Get system settings |
| POST | /api/admin/settings | (Auth) Update a system setting |

All `/api/admin/*` endpoints require header `X-Admin-Password: <password>` when `ADMIN_PASSWORD` is configured.

## Generate a Test Report

1. Open http://localhost:5173
2. Fill in the form and click "Generate PPT"
3. The frontend immediately gets a job_id and starts polling
4. Status updates: queued → running → success (or failed)
5. When complete, download links appear

## Job States

| Status | Meaning |
|--------|---------|
| `queued` | Job is waiting in the Redis queue |
| `running` | Worker picked up the job, Claude Code is generating |
| `success` | Generation complete, files ready for download |
| `failed` | Generation failed, check error message and logs |

## Where Generated Files Are

```
backend/outputs/{job_id}/
  ├── index.html         ← The generated presentation
  ├── standalone.html    ← Self-contained (no external deps)
  ├── prompt.txt         ← The prompt sent to Claude Code
  ├── logs.txt           ← Claude Code stdout/stderr
  └── ...                ← Other generated assets
```

ZIP files: `backend/outputs/{job_id}.zip`

## Debugging

If generation fails:

1. Check the job status via `GET /api/jobs/{job_id}` for error_message
2. Check `backend/outputs/{job_id}/logs.txt` for Claude Code output
3. Check `backend/outputs/{job_id}/prompt.txt` to see the prompt
4. Ensure Redis is running: `redis-cli ping` → PONG
5. Ensure the worker is running: check Terminal 3 for output
6. Ensure html-ppt-skill is installed: `npx skills list`
7. Ensure Claude Code CLI works: `claude --version`
