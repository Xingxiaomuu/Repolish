# Slidehttp — Railway Deployment Guide (Phase 5B)

Separation-of-concerns deployment with PostgreSQL, Redis, Backend (API-only), Worker, and S3-compatible object storage. No shared volume needed.

## Architecture

```
                         ┌──────────────────────────────────────────┐
  Internet               │  Railway Project "slidehttp"             │
                         │                                          │
  User ───► Frontend     │  Service: backend (API)                  │
  (Vercel/static)        │    uvicorn main:app :8000                │
                         │    ├─ Auth (JWT + bcrypt)                │
                         │    ├─ Job CRUD, rate limiting            │
                         │    ├─ Download → presigned S3 URLs       │
                         │    └─ Admin API                          │
                         │                                          │
                         │  Service: worker                         │
                         │    python worker_supervisor.py           │
                         │    ├─ Dequeues from Redis "generation"   │
                         │    ├─ Creates in /tmp/htmlppt-jobs/      │
                         │    ├─ Spawns Claude Code + html-ppt-skill│
                         │    └─ Uploads outputs to S3/R2           │
                         │                                          │
                         │  Plugin: PostgreSQL                      │
                         │    users, jobs, usage_records, settings  │
                         │    (shared by backend + worker)          │
                         │                                          │
                         │  Plugin: Redis                           │
                         │    RQ queue "generation"                 │
                         │    (shared by backend + worker)          │
                         │                                          │
                         │  External: Cloudflare R2 (or S3)         │
                         │    jobs/{job_id}/index.html              │
                         │    jobs/{job_id}/standalone.html         │
                         │    jobs/{job_id}/{job_id}.zip            │
                         │    jobs/{job_id}/logs.txt                │
                         │    jobs/{job_id}/quality_report.json     │
                         └──────────────────────────────────────────┘
```

---

## Step 1: Prerequisites

1. A [Railway](https://railway.app) account
2. Your project pushed to a **GitHub repository**
3. An [Anthropic API key](https://console.anthropic.com/) (Claude Code needs this)
4. A [Cloudflare R2](https://developers.cloudflare.com/r2/) bucket (or any S3-compatible storage)
   - Create a bucket (e.g., `slidehttp-outputs`)
   - Generate an Access Key ID and Secret Access Key
   - Note the endpoint URL (`https://<account>.r2.cloudflarestorage.com`)

---

## Step 2: Connect GitHub to Railway

1. Go to [railway.app/dashboard](https://railway.app/dashboard) → **New Project**
2. Select **Deploy from GitHub repo**
3. Configure GitHub App access if needed
4. Select your Slidehttp repository
5. Railway detects the `Dockerfile` at repo root

---

## Step 3: Add PostgreSQL

1. In your project dashboard, click **New** → **Database** → **PostgreSQL**
2. Railway auto-provisions PostgreSQL and adds `DATABASE_URL` as a **shared variable**
3. Tables (`users`, `jobs`, `usage_records`, `system_settings`) are auto-created on first startup by `init_db()`

---

## Step 4: Add Redis

1. Click **New** → **Database** → **Redis**
2. Railway auto-provisions Redis and adds `REDIS_URL` as a shared variable

---

## Step 5: Configure the Backend Service

1. Railway creates an initial service from your Dockerfile. Click it → **Settings** → rename to **`backend`**
2. Under **Deploy**:
   - **Start command**: leave default (Dockerfile CMD runs `uvicorn main:app --host 0.0.0.0 --port 8000`)
   - **Root directory**: `/` (repository root)
3. Under **Networking**, ensure a public domain is generated (for API access)
4. Add **service-specific** or **shared** variables (see Step 7)

---

## Step 6: Create the Worker Service

1. Click **New** → **Service** → **Deploy from GitHub repo** (same repo)
2. Rename it to **`worker`**
3. Under **Deploy**:
   - **Start command**: `python worker_supervisor.py`
   - **Root directory**: `/`
4. The worker does **NOT** need a public domain (no HTTP port exposed)
5. The worker needs the same `DATABASE_URL`, `REDIS_URL`, and S3 variables as the backend

---

## Step 7: Configure Environment Variables

### Shared Variables (set in project **Variables** tab)

| Variable | Value | Notes |
|---|---|---|
| `DATABASE_URL` | (auto-set by PostgreSQL plugin) | Do NOT override |
| `REDIS_URL` | (auto-set by Redis plugin) | Do NOT override |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | **REQUIRED** — Claude Code API key |
| `JWT_SECRET` | *32+ char random string* | For JWT token signing |
| `ADMIN_PASSWORD` | *your admin password* | Admin panel access |
| `FREE_GENERATIONS_PER_MONTH` | `3` | Rate limit per user |
| `CLAUDE_TIMEOUT` | `1800` | Max seconds per generation |
| `WORKER_COUNT` | `2` | Worker processes in worker service |
| `STORAGE_PROVIDER` | `s3` | "s3" for R2, "local" for local dev |
| `S3_BUCKET` | `slidehttp-outputs` | Your R2 bucket name |
| `S3_ENDPOINT` | `https://<account>.r2.cloudflarestorage.com` | R2 endpoint |
| `S3_ACCESS_KEY_ID` | *R2 access key ID* | From Cloudflare dashboard |
| `S3_SECRET_ACCESS_KEY` | *R2 secret key* | From Cloudflare dashboard |
| `S3_REGION` | `auto` | Use "auto" for R2 |
| `S3_PUBLIC_BASE_URL` | `https://pub-<hash>.r2.dev` | (Optional) R2 public URL |

### Backend-Specific Variables

| Variable | Value | Notes |
|---|---|---|
| `PUBLIC_BACKEND_URL` | `https://backend-xxx.up.railway.app` | Set after first deploy |
| `FRONTEND_URL` | `https://your-frontend.vercel.app` | For CORS |
| `CORS_ORIGINS` | `https://your-frontend.vercel.app,http://localhost:5173` | Comma-separated |

---

## Step 8: Verify Deployment

### 8a. Health Check

```bash
curl https://YOUR_BACKEND_URL/api/health
```

Expected:
```json
{
  "status": "pass",
  "checks": {
    "api": "ok",
    "database": "connected",
    "redis": "connected",
    "storage": "s3://slidehttp-outputs",
    "claude_command": "found (/usr/local/bin/claude)",
    "html_ppt_skill": "exists (/app/.agents/skills/html-ppt/SKILL.md)",
    "python_version": "3.12.x",
    "worker_count": "2"
  }
}
```

### 8b. Worker Health Check

```bash
# SSH into worker or run from deploy logs:
python scripts/worker_health_check.py
```

### 8c. Smoke Test

From your local machine:

```bash
cd html-ppt-app/backend
pip install boto3 psycopg2-binary

python scripts/smoke_test_remote.py --base-url https://YOUR_BACKEND_URL
```

This verifies the full pipeline: register → create job → poll → download via presigned URLs → auth enforcement.

---

## Step 9: Deploy Frontend (Separate)

### Vercel (recommended)

1. Import your GitHub repo into Vercel
2. **Root Directory**: `html-ppt-app/frontend`
3. **Build Command**: `npm run build`
4. **Output Directory**: `dist`
5. Environment variable: `VITE_API_BASE_URL` = `https://YOUR_BACKEND_URL`

---

## Step 10: View Logs

```bash
# Railway CLI
railway login
railway link
railway logs --service backend
railway logs --service worker
```

Or use the Railway dashboard → Deployments → Log Explorer.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Health: `database: error` | PostgreSQL plugin not added | Add PostgreSQL in project |
| Health: `redis: error` | Redis plugin not added | Add Redis in project |
| Health: `storage: error` | S3 credentials wrong | Check S3_* variables |
| Health: `claude_command: NOT FOUND` | Claude Code CLI install failed | Check Docker build logs |
| Health: `html_ppt_skill: NOT FOUND` | `.agents/` not copied | Check `COPY .agents/` in Dockerfile |
| Job stuck in `queued` | Worker not running | Check worker logs |
| Job `failed` with timeout | Claude Code took >30 min | Increase `CLAUDE_TIMEOUT` |
| Download returns 401 | Auth required (new in 5B) | Include JWT Bearer token |
| Download returns 403 | Wrong user accessing job | Only job owner or admin can download |
| S3 upload fails | Worker can't reach R2 | Check network, S3_ENDPOINT, credentials |
| Smoke test register 500 | Database migration issue | Check backend logs |

---

## Architecture Changes from Phase 5A

| Aspect | Phase 5A (old) | Phase 5B (new) |
|---|---|---|
| Database | SQLite on shared Volume | PostgreSQL plugin |
| File storage | `/data/outputs` on Volume | S3/R2 object storage |
| Backend-Worker sharing | Shared Volume mount | PostgreSQL + Redis + S3 |
| Download auth | None (public) | JWT required |
| Preview | Static `/outputs/` mount | `/api/preview/{id}` (auth) |
| Volume needed | Yes | No |
| Backend reads worker files | Yes (shared volume) | No (via S3 presigned URLs) |

---

## Cost Notes (May 2026)

- Railway **Hobby plan** ($5/month credit): covers small setups
- Backend API: ~512 MB RAM, 0.1-0.5 vCPU
- Worker: ~1-2 GB RAM (Claude Code), 0.5-1 vCPU
- PostgreSQL plugin: included in Railway usage
- Redis plugin: included in Railway usage
- Cloudflare R2: free tier (10 GB storage, 10M Class A ops/month)
- Anthropic API: pay-per-use, depends on generation volume
