# Slidehttp — Railway Deployment Guide (Phase 5A)

Minimal public deployment for small-scale testing. Single Docker image, two Railway services
(API + worker), shared Redis plugin, persistent volume for SQLite and outputs.

## Architecture

```
                    ┌─────────────────────────────────────┐
  Internet          │  Railway Project "slidehttp"        │
                    │                                     │
  User ──► Frontend │  Service: backend (API)             │
  (Vercel/static)   │    uvicorn main:app :8000           │
                    │    └─ reads/writes /data/app.db     │
                    │    └─ enqueues to Redis "generation" │
                    │                                     │
                    │  Service: worker                    │
                    │    python worker_supervisor.py      │
                    │    └─ dequeues from Redis            │
                    │    └─ spawns Claude Code CLI         │
                    │    └─ writes to /data/outputs/       │
                    │                                     │
                    │  Plugin: Redis                      │
                    │    queue + RQ state                  │
                    │                                     │
                    │  Volume: /data (shared mount)       │
                    │    ├── app.db                       │
                    │    └── outputs/{job_id}/            │
                    └─────────────────────────────────────┘
```

---

## Step 1: Prerequisites

1. A [Railway](https://railway.app) account
2. Your project pushed to a **GitHub repository** (public or private)
3. An [Anthropic API key](https://console.anthropic.com/) (Claude Code needs this)
4. Claude Code CLI usable locally: `npm install -g @anthropic-ai/claude-code` (already in Dockerfile)

---

## Step 2: Connect GitHub to Railway

1. Go to [railway.app/dashboard](https://railway.app/dashboard) and click **New Project**
2. Select **Deploy from GitHub repo**
3. Click **Configure GitHub App** if you haven't already — grant Railway access to your account or specific repos
4. Select the repository `Slidehttp` (or whatever you named it)
5. Railway will detect the `Dockerfile` at the repo root

> Railway initially creates one service from the Dockerfile. We'll split into two services in Step 3.

---

## Step 3: Create the Backend API Service

1. In your project dashboard, you'll see one service (named after your repo or Dockerfile)
2. Click on it → **Settings** → rename it to **`backend`**
3. Under **Deploy**, make sure:
   - **Source**: GitHub repo (auto-deploy on push: **enabled**)
   - **Root directory**: `/` (repository root)
   - **Start command**: leave as default (the Dockerfile `CMD` already runs uvicorn)
4. Click **Deploy** to trigger the first build

> The default `CMD` in Dockerfile is `uvicorn main:app --host 0.0.0.0 --port 8000`, so the API service works out of the box.

---

## Step 4: Add Redis

1. In your project dashboard, click **New** → **Database** → **Redis**
2. Railway automatically provisions Redis and adds `REDIS_URL` (with the actual connection string) as a **shared variable** visible to all services in this project
3. No manual configuration needed — `REDIS_URL` in the provided `.env.production.example` maps directly to what Railway provides
4. Both `backend` and `worker` services will auto-connect via this shared variable

---

## Step 5: Add a Persistent Volume

1. In your project dashboard, click on the **backend** service
2. Go to **Settings** → **Volumes** → **Add Volume**
3. Configure:
   - **Mount path**: `/data`
   - **Volume name**: `data` (or any name you prefer)
4. Click **Add Volume**
5. This volume is where SQLite (`/data/app.db`) and generated outputs (`/data/outputs/`) live

> **IMPORTANT**: If you don't add a volume, the database and all generated files will be lost on every deploy. The volume persists across deploys. Both services need to share the same volume — Railway currently supports this by attaching the same named volume to multiple services in the project.

---

## Step 6: Create the Worker Service

1. In your project dashboard, click **New** → **Service** → **Deploy from GitHub repo**
2. Select the **same repository**
3. Click on this new service → **Settings** → rename it to **`worker`**
4. Under **Deploy** → **Start command**, override with:
   ```
   python worker_supervisor.py
   ```
5. Under **Volumes**, attach the same volume as Step 5:
   - **Mount path**: `/data`
   - **Volume name**: `data` (same name as above)
6. This service:
   - Does **NOT** need a public domain (no HTTP port needed)
   - Only needs the Redis connection + volume mount + Anthropic API key
   - Will pull from the same "generation" queue

> The worker service doesn't expose a port. Railway will show it as "healthy" based on the process running (not crashing). There's no HTTP health check for the worker.

---

## Step 7: Configure Environment Variables

Go to the project **Variables** tab (shared across all services). Add these:

| Variable | Value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | **REQUIRED** — get from console.anthropic.com |
| `DATABASE_URL` | `sqlite:////data/app.db` | Points to the volume mount |
| `REDIS_URL` | (auto-set by Railway Redis plugin) | Do NOT override manually |
| `JWT_SECRET` | *generate a random 32+ char string* | Used for login tokens |
| `JWT_EXPIRE_DAYS` | `7` | Token lifetime |
| `ADMIN_PASSWORD` | *your admin password* | For the /admin page |
| `OUTPUT_DIR` | `/data/outputs` | Generated PPT files |
| `PUBLIC_BACKEND_URL` | `https://backend-xxx.railway.app` | Set AFTER first deploy (see domain in backend service) |
| `FRONTEND_URL` | `https://your-frontend.vercel.app` | Or `*` if testing with localhost |
| `CORS_ORIGINS` | `https://your-frontend.vercel.app,http://localhost:5173` | Comma-separated allowed origins |
| `FREE_GENERATIONS_PER_MONTH` | `3` | Monthly free limit per user |
| `WORKER_COUNT` | `2` | Number of RQ workers in the worker service |
| `CLAUDE_CODE_COMMAND` | `claude` | CLI command (npm global install) |
| `CLAUDE_TIMEOUT` | `1800` | Max seconds per generation (30 min) |

> **Service-specific variables**: You can also set variables only on the `backend` or `worker` service if they differ, but shared variables are simpler.

---

## Step 8: Verify Deployment

### 8a. Health Check

Once the backend deploys, Railway assigns it a public domain like:
`https://backend-production-xxxx.up.railway.app`

Check health:
```bash
curl https://YOUR_BACKEND_URL/api/health
```

Expected response:
```json
{
  "status": "pass",
  "checks": {
    "api": "ok",
    "database": "connected",
    "redis": "connected",
    "output_dir": "writable (/data/outputs)",
    "claude_command": "found (/usr/local/bin/claude)",
    "html_ppt_skill": "exists (/app/.agents/skills/html-ppt/SKILL.md)",
    "python_version": "3.12.x",
    "worker_count": "2"
  }
}
```

If any check shows `"error"` or `"NOT FOUND"`, check the logs (Step 9).

### 8b. Smoke Test

Run the smoke test script from your local machine:

```bash
cd html-ppt-app/backend
pip install requests  # if not already installed

python scripts/smoke_generate.py --base-url https://YOUR_BACKEND_URL
```

This script:
1. Hits `/api/health` to verify all services
2. Registers a test user (or logs in if already exists)
3. Creates a minimal 3-slide job via `POST /api/jobs`
4. Polls `GET /api/jobs/{job_id}` until success or timeout (10 min)
5. Verifies all download URLs return HTTP 200
6. Checks that `quality_report.json` is present

Expected output ends with:
```
============================================================
SMOKE TEST PASSED — All outputs generated successfully.
Job ID: abc123...
Preview: https://YOUR_BACKEND_URL/outputs/abc123.../index.html
============================================================
```

> **Note**: The first run may take 5-10 minutes as Claude Code generates the deck. Subsequent runs are often faster.

---

## Step 9: View Logs

### Railway Dashboard (Web)

1. Go to your project dashboard
2. Click on the **backend** or **worker** service
3. Click the **Deployments** tab
4. Click on any deployment to see build + runtime logs
5. Use the **Log Explorer** for real-time streaming logs

### Railway CLI

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Link to your project
railway link

# Stream logs from backend
railway logs --service backend

# Stream logs from worker
railway logs --service worker
```

---

## Step 10: Deploy Frontend (Separate)

The frontend is a static React SPA. Recommended hosting:

### Option A: Vercel (simplest)

1. Import your GitHub repo into Vercel
2. Set **Root Directory** to `html-ppt-app/frontend`
3. Set **Build Command**: `npm run build`
4. Set **Output Directory**: `dist`
5. Add environment variable: `VITE_API_BASE_URL` = `https://YOUR_BACKEND_URL`

### Option B: Railway static serve

You can add a third Railway service that serves the built frontend. However, Vercel is better optimized for static SPAs.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Health: `database: error` | Volume not mounted or path wrong | Check `/data` volume mount exists in service settings |
| Health: `redis: error` | Redis plugin not added or `REDIS_URL` missing | Add Redis plugin in project; check shared variables |
| Health: `claude_command: NOT FOUND` | Claude Code CLI not installed | Check Dockerfile build logs; `npm install -g @anthropic-ai/claude-code` may have failed |
| Health: `html_ppt_skill: NOT FOUND` | `.agents/` directory not copied into image | Check that `COPY .agents/ /app/.agents/` ran in Dockerfile |
| Job stuck in `queued` forever | Worker service not running or Redis not connected | Check worker logs: `railway logs --service worker` |
| Job `failed` with timeout | Claude Code took >30 min | Increase `CLAUDE_TIMEOUT` env var |
| `ANTHROPIC_API_KEY` error | Key not set or invalid | Verify key in project Variables; check for typos |
| Build fails: out of memory | Docker build OOM | In Railway settings, bump service memory to 2+ GB |
| "Email already registered" on smoke test | User from previous smoke test exists | Smoke test handles this (400 → login instead) |

---

## Cleanup

To tear down everything:
1. Railway dashboard → Project Settings → **Delete Project**
2. This removes all services, the Redis instance, and the volume
3. Your GitHub repo is unaffected

---

## Cost Notes (May 2026)

- Railway **Hobby plan** ($5/month credit): ~$5-10/month total for all 3 services + Redis
- Backend API service: ~512 MB RAM, 0.1-0.5 vCPU → $2-4/month
- Worker service: ~1-2 GB RAM (Claude Code needs memory), 0.5-1 vCPU → $3-5/month
- Redis plugin: included in usage cost or separate small charge
- Volume (1 GB): usually free tier or minimal cost
- Anthropic API: Claude Code uses your API key, cost depends on usage
