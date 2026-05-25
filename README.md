# Slidehttp — HTML PPT Generator

Local HTML presentation generator powered by Claude Code + html-ppt-skill.

## Quick Start (LAN — Phase 4G)

### 1. Install dependencies

```bash
# Backend
cd html-ppt-app/backend
pip install -r requirements.txt

# Frontend
cd html-ppt-app/frontend
npm install
```

### 2. Configure

Copy `.env.example` to `.env` and customize:

```bash
cd html-ppt-app/backend
cp .env.example .env
```

Key settings:
- `ADMIN_PASSWORD` — set a password for the admin dashboard
- `FREE_GENERATIONS_PER_MONTH` — free generations per user per month (default 3)
- `JWT_SECRET` — secret key for JWT token signing (change in production!)
- `JWT_EXPIRE_DAYS` — how long login tokens last (default 7)
- `CLAUDE_CODE_COMMAND` — path to Claude Code CLI

### 3. Start (4 terminals)

**Terminal 1 — Redis:**
```bash
redis-server
```

**Terminal 2 — Backend API:**
```bash
cd html-ppt-app/backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 3 — Worker Supervisor (default 2 workers):**
```bash
cd html-ppt-app/backend
python worker_supervisor.py
# Or: python worker_supervisor.py --count 3
```

**Terminal 4 — Frontend:**
```bash
cd html-ppt-app/frontend
npm run dev -- --host 0.0.0.0
```

Open http://localhost:5173

Admin dashboard: http://localhost:5173/admin

### 4. First-Time Setup — Register an account

Open http://localhost:5173 → You'll see the login page with "开始你的 HTML 之旅".

1. Click **Register**
2. Fill in Name, Email, Password (min 6 chars)
3. Register → then Login
4. You'll be taken to the HTML PPT Studio main interface

### 5. LAN Access

**Find your LAN IP:**

| OS | Command |
|---|---|
| Windows | `ipconfig` — look for "IPv4 Address" under Wi-Fi adapter |
| macOS / Linux | `ifconfig` or `ip addr` — look for `inet 192.168.x.x` |

**Access from other devices on the same Wi-Fi:**

```
http://<YOUR_LAN_IP>:5173
```

Example: `http://192.168.1.100:5173`

## Security Notice

This is a **LAN-only testing version**. Do **NOT** expose to the public internet.

- Passwords are hashed with bcrypt before storage
- JWT tokens signed with `JWT_SECRET` (change the default!)
- Admin dashboard uses separate password authentication (X-Admin-Password header)
- Rate limiting is per-user, per-month (default 3 generations)
- Do NOT upload sensitive business data or trade secrets
- Full authentication, payment, and permission systems will be added in Phase 5

## Features

- **Phase 4G UI**: Pink-blue bright theme, ChatGPT-style sidebar layout
- **Login / Register**: JWT-based auth with bcrypt password hashing
- **Template Cards**: 2 preset cards (半导体产业报告, 亚太音频市场调研报告) — click to auto-fill
- **Mobile Responsive**: Sidebar drawer, stacked forms, compact tables on mobile
- **i18n**: Chinese / English toggle in sidebar
- Submit report content + topic → Claude Code generates HTML presentation
- Short input: simple prompt → HTML PPT
- Long input (>=1000 chars): 6-step pipeline (clean → plan → pack → prompt → generate → check)
- Standalone HTML export (copy to any computer, open offline)
- ZIP download with both versions + logs
- Multi-worker parallel processing (Redis + RQ)
- Admin dashboard with user management, usage stats, quality reports
- Rate limiting: free generations per user per month
- Quality checker: 8-category automated quality scoring

## API

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | / | - | Health check |
| POST | /api/auth/register | - | Register new user |
| POST | /api/auth/login | - | Login, get JWT token |
| GET | /api/auth/me | JWT | Get current user info |
| POST | /api/auth/logout | - | Logout (client-side token discard) |
| POST | /api/jobs | JWT | Create job (topic, content, ...) |
| GET | /api/jobs/{job_id} | - | Job status + download URLs |
| GET | /api/jobs | - | Recent jobs list |
| GET | /api/my/jobs | JWT | Current user's jobs |
| GET | /api/my/usage | JWT | Current user's monthly usage |
| GET | /api/admin/summary | Admin | System summary stats |
| GET | /api/admin/jobs | Admin | Paginated job list with filters |
| GET | /api/admin/jobs/{job_id} | Admin | Full job detail |
| GET | /api/admin/queue | Admin | Queue / worker status |
| GET | /api/admin/users | Admin | User list with usage stats |
| GET | /api/admin/stats | Admin | 7-day stats, total usage |
| GET | /api/admin/settings | Admin | System settings |
| POST | /api/admin/settings | Admin | Update settings |
| GET | /api/download/{job_id}/html | - | Download index.html |
| GET | /api/download/{job_id}/standalone | - | Download standalone.html |
| GET | /api/download/{job_id}/zip | - | Download ZIP |

## Testing Checklist

- [ ] Local machine: http://localhost:5173 opens → login page with "开始你的 HTML 之旅"
- [ ] Register a new account → login → enter Studio page
- [ ] Sidebar shows user info, navigation (新建生成 / 我的任务 / 用量统计)
- [ ] Click template card → form auto-fills → can modify fields
- [ ] Fill topic + content → Generate PPT → job queued
- [ ] Job processes → status updates → download links appear
- [ ] Preview standalone → copy to another computer → opens correctly
- [ ] Quality hints shown for warning/fail status
- [ ] 4th generation → "monthly limit reached" error
- [ ] My Jobs page shows only current user's tasks
- [ ] Usage page shows correct counts (used/remaining/success/failed)
- [ ] Logout → back to login page → can login again
- [ ] Chinese/English toggle switches UI language
- [ ] Mobile view: hamburger menu → sidebar drawer → form stacks vertically
- [ ] Another device on same Wi-Fi can access http://<IP>:5173
- [ ] Another device can register and submit a generation job
- [ ] Admin page: http://localhost:5173/admin → login → see users, jobs, stats, quality
- [ ] 2 workers visible in queue status (when supervisor running)
- [ ] 3rd concurrent job queues correctly (while 2 workers are busy)

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React + TypeScript + Vite + react-router-dom |
| Backend | Python FastAPI |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Queue | Redis + RQ (SimpleWorker for Windows) |
| Database | SQLite (WAL mode) |
| AI | Claude Code CLI + html-ppt-skill |

## Project Phases

| Phase | Status |
|---|---|
| Phase 0 | Manual Claude Code generation |
| Phase 1 | Local web UI + API |
| Phase 2 | standalone.html export |
| Phase 3 | Skill template expansion (designed) |
| Phase 4A | Async queue (Redis + RQ + SQLite) |
| Phase 4B | Multi-worker parallel processing |
| Phase 4C | Admin dashboard + token estimation |
| Phase 4D | Long text pipeline (clean/plan/pack/prompt) |
| Phase 4E | Quality checker (8 categories) |
| Phase 4F | LAN testing (users + rate limiting) |
| Phase 4G | UI upgrade, login/register, mobile, template cards |
| Phase 5 | Public deployment (planned) |
