# Slidehttp — HTML PPT Generator

## CLAUDE MD 准则
阶段总览表
关键设计 + 架构图
核心技术决策
API 表
任务状态表
操作手册（4 终端启动命令、局域网访问）
每任务输出文件列表
去掉所有 Phase 的详细展开（文件清单、验收测试步骤等），具体实现直接看代码即可

## 项目阶段

| 阶段 | 状态 |
|---|---|
| Phase 0 | 手动 Claude Code + html-ppt-skill 生成 HTML PPT |
| Phase 1 | 本地前后端，用户输入 → Claude Code → 生成下载 |
| Phase 2 | standalone.html 导出，解决跨电脑打开问题 |
| Phase 3 | 扩展 skill 模板体系（设计完成，待实施） |
| Phase 4A | 异步任务队列架构（Redis + RQ + SQLite）✅ |
| Phase 4B | 多 worker 并行 + 队列管理 ✅ |
| Phase 4C | 管理页面、token 用量估算、worker 配置 ✅ |
| Phase 4D | 长文本报告生成链路（输入清洗 + Deck Plan + Context Packing）✅ |
| Phase 4E | Quality Check 强化（8 类自动化检查 + DB 持久化 + 测试）✅ |
| Phase 4F | 局域网小范围测试（用户+限流+LAN 访问）✅ |
| Phase 4G | 前端升级、登录注册、移动端适配、模板卡片 ✅ |
| Phase 5A | Railway 公网部署（Dockerfile + 双服务 + Redis + Volume + Smoke Test）✅ |
| Phase 5B | Railway 分离式部署（PostgreSQL + Redis + S3/R2 对象存储、无共享 Volume）✅ |
| Phase 5C | 生产 Bug 修复 + 部署踩坑总结（download_token / _bearer / Railway 快照）✅ |

---

## 关键设计

```
前端 = 用户意图输入（React + TypeScript）
后端 = Prompt 编排 + 文件管理 + 调用 Claude Code（Python FastAPI）
Claude Code + html-ppt-skill = 真正生成 HTML PPT
Redis + RQ = 异步任务队列
本地: SQLite (WAL) = 任务持久化
Railway: PostgreSQL + S3/R2 = 共享状态 + 对象存储
```

---

## 架构概览

### 整体流程

```
Frontend → 用户注册/登录 → JWT token (localStorage)
  → POST /api/auth/register (name, email, password) → bcrypt hash → SQLite
  → POST /api/auth/login → JWT token (7天过期) → 后续请求带 Authorization: Bearer <token>

Frontend (已登录) → POST /api/jobs (topic, content... + Bearer token)
  → JWT 解析 user_id
  → 检查 usage_records 本月用量 (默认每月 3 次)
  → usage_count +1
  → SQLite: INSERT job (status=queued, user_id)
  → Redis/RQ: enqueue generate_deck(job_id)
    → Worker 领取任务
      → 短输入：claude_runner.build_prompt() 生成简单 prompt
      → 长输入（≥1000字）：运行 6 步 Pipeline
          Step 1: input_cleaner → 正则提取章节/实体/表格
          Step 2: deck_planner → 规划每页结构
          Step 3: context_packer → 每页绑定原文片段
          Step 4: prompt_builder → 生成带计划+上下文的 prompt
          Step 5: Claude Code + html-ppt-skill → index.html
      → html_inliner → standalone.html
      → zip 打包
      → Step 6: quality_checker → 质量报告（A-H 8 类检查）
      → S3 模式: 上传所有产物到对象存储，写入 storage_key 到 DB
      → DB: UPDATE job (status=success/failed, quality_*, *_key)
  ← Frontend 每 2s 轮询 GET /api/jobs/{job_id}
```

### 多 Worker 并行

```
worker_supervisor.py (默认 2 个 worker)
  ├── 启动时清理 Redis 中所有残留 worker (rq:worker:*)
  ├── 重置 DB 中 stuck 的 "running" 任务为 "queued"
  ├── worker-1 (SimpleWorker) ── 共享 Redis "generation" 队列
  └── worker-2 (SimpleWorker) ── 共享 Redis "generation" 队列
```

### 文件结构

```
backend/
  main.py              FastAPI 入口
  settings.py          pydantic-settings 配置（含 FREE_GENERATIONS_PER_MONTH）
  database.py          SQLAlchemy + WAL + 自动迁移（users, usage_records, jobs）
  models.py            Job / User / UsageRecord ORM + Pydantic 响应模型
  worker.py            RQ Worker（Windows: SimpleWorker）
  worker_supervisor.py 多 Worker 管理器
  tasks/
    generate_deck.py   RQ 任务：完整生成流程编排
  services/
    admin_auth.py      Admin API 密码验证（Header 方式）
    claude_runner.py   Claude Code 子进程调用（stdin pipe）
    file_manager.py    输出目录 + zip 管理
    html_inliner.py    index.html → standalone.html
    token_estimator.py CJK 感知的 token 估算（ASCII/4, 中日韩/1.5）
    storage/
      __init__.py         存储模块导出
      storage_client.py    抽象 StorageClient + LocalStorageClient + S3StorageClient
    pipeline/
      input_cleaner.py     Step 1：输入清洗（纯正则，无 LLM）
      deck_planner.py      Step 2：页面规划（规则引擎）
      context_packer.py    Step 3：上下文打包
      prompt_builder.py    Step 4：生成 Prompt 构建
      quality_checker.py   Step 6：质量检查
  outputs/{job_id}/    每个任务独立输出目录（local 模式）
  scripts/
    smoke_generate.py         Phase 5A 冒烟测试（注册→创建→轮询→验证输出）
    smoke_test_remote.py      Phase 5B 远程冒烟测试（S3 模式全链路）
    worker_health_check.py    Phase 5B Worker 健康检查

frontend/
  src/
    main.tsx           路由入口（登录 → Studio 主界面）
    LoginPage.tsx      登录/注册页（"开始你的 HTML 之旅"）
    MainLayout.tsx     ChatGPT 式侧边栏 + 主工作区布局
    StudioPage.tsx     生成表单 + 模板卡片 + 结果展示（原 App.tsx）
    MyJobsPage.tsx     当前用户任务列表
    UsagePage.tsx      本月用量统计
    AdminPage.tsx      管理页面（汇总卡片 + 任务表 + 详情 + 设置）
    presets.ts         两套模板卡片预设（半导体/音频市场）
    api.ts             API 调用层（含 JWT token 管理）
    styles.css         粉蓝明亮色系 + 移动端响应式
```

---

## 核心技术决策

- **Prompt 传入 Claude Code**：用 Python `subprocess.run(input=prompt)` 走 stdin pipe，不用 PowerShell、不用 shell、没有命令行长度限制
- **Windows 兼容**：RQ 用 `SimpleWorker`（进程内执行，因为 Windows 无 `os.fork()`）。多个 worker = 多个 `python worker.py` 进程共享 Redis 队列
- **Job 隔离**：每个 job 独立 `outputs/{job_id}/` 目录，互不干扰
- **数据库并发**：SQLite WAL 模式 + `busy_timeout=5000ms`，worker 写、API 读互不阻塞
- **长文本处理**：≥1000 字符的报告走 6 步 Pipeline，保留原文结构/数据/实体；短输入走简单 prompt
- **Pipeline 全部无 LLM 依赖**：Steps 1-3 和 Step 6 都是纯规则/正则，不额外消耗 token
- **Token 用量估算**：CJK 感知估算（ASCII ~4 chars/token, 中日韩 ~1.5 chars/token），精度优于简单 chars/4；未来接入真实 API 返回值时新增字段，不覆盖估算
- **Admin 认证**：通过 `X-Admin-Password` header + `ADMIN_PASSWORD` 环境变量；未配置时无密码保护
- **质量检查**：生成后自动运行 8 类检查（A 文件、B HTML 结构、C Placeholder、D 空页面、E 实体保留、F 数据保留、G 页源对应、H Standalone 完整性）；结果持久化到 DB + quality_report.json；有 pipeline 数据时运行全量检查，否则仅运行结构/文件/占位符检查
- **用户认证**：JWT (python-jose) + bcrypt 原生 API 密码哈希（无 passlib）；`JWT_SECRET` 和 `JWT_EXPIRE_DAYS` 环境变量控制；token 存前端 localStorage，每次请求带 `Authorization: Bearer <token>` header
- **用户与限流**：注册用户按月统计用量；`FREE_GENERATIONS_PER_MONTH` 环境变量控制每月每用户免费次数（默认 3）；超出返回 429；失败任务暂不自动退回，admin 页面可手动审查
- **前端布局**：ChatGPT 式侧边栏 + 主工作区；侧边栏在移动端变为抽屉式；所有生成输入在一个页面内呈现；两套模板卡片点击即可自动填充表单
- **国际化**：中/英切换按钮在侧边栏底部，通过 `lang` state 控制各组件文案
- **Admin 与普通用户分离**：Admin 仍用 `X-Admin-Password` header 验证，与 JWT 用户登录互不影响
- **双模式存储（Phase 5B）**：`STORAGE_PROVIDER` 环境变量控制 — `local` 走本地文件 + FileResponse（本地开发），`s3` 走 S3/R2 对象存储 + presigned URL 重定向（Railway 生产）、下载路由需 JWT 认证 + 任务归属校验、Worker 生成后在 /tmp 临时目录处理再上传 S3

---

## 数据库

- 本地 (`STORAGE_PROVIDER=local`)：SQLite 文件 `backend/app.db`，首次启动自动创建
- Railway (`STORAGE_PROVIDER=s3`)：PostgreSQL，Railway plugin 自动提供 `DATABASE_URL`
- Dialect 自动检测：代码根据 `DATABASE_URL` 前缀自动配置 SQLite PRAGMA 或 PostgreSQL 连接池
- 表 `jobs`：存储所有请求参数、输出路径、worker 信息、时间戳、状态、token 估算、质量检查结果
  - 字段：`user_id`、`worker_name`、`queue_position`、`retry_count`、`estimated_input_tokens`、`estimated_output_tokens`、`model_name`、`generation_prompt_chars`、`generated_html_chars`、`quality_status`、`quality_score`、`quality_warnings_count`、`quality_errors_count`
  - Phase 5B 新增：`index_html_key`、`standalone_html_key`、`zip_key`、`logs_key`、`quality_report_key`、`deck_plan_key`、`packed_context_key`、`input_cleaned_key`、`generation_prompt_key`（S3 对象存储 key）
  - Phase 5C 新增：`download_token`（随机令牌，嵌入下载/预览 URL 实现无需 JWT 的浏览器下载认证）
- 表 `users`（Phase 4G）：`id`, `name`, `email` (unique), `password_hash`, `last_login_at`, `created_at`
- 表 `usage_records`（Phase 4F）：`id`, `user_id`, `month` (YYYY-MM), `generation_count`
- 表 `system_settings`：key-value 配置存储（如 `desired_worker_count`）

---

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | / | 根端点，返回版本信息 |
| GET | /api/health | 全面健康检查（API/DB/Redis/输出目录/Claude CLI/Skill/Python版本/Worker数）|
| POST | /api/auth/register | 注册（name, email, password≥6位 → bcrypt hash）|
| POST | /api/auth/login | 登录 → JWT token（7天过期）+ user 信息 |
| GET | /api/auth/me | (JWT) 返回当前用户信息 |
| POST | /api/auth/logout | 登出（客户端丢弃 token）|
| POST | /api/jobs | (JWT) 创建任务 → 入队 → 返回 `{job_id, status:"queued"}` |
| GET | /api/jobs/{job_id} | 任务状态 + 输出 URL（成功时）+ 排队位置（等待时）|
| GET | /api/jobs | 最近任务列表（默认 50 条）|
| GET | /api/my/jobs | (JWT) 当前用户自己的任务列表 |
| GET | /api/my/usage | (JWT) 当前用户本月用量（已用/限额/剩余/成功/失败）|
| GET | /api/preview/{job_id} | (JWT) 预览生成的 PPT（?type=standalone）|
| GET | /api/jobs/{job_id}/artifacts | (JWT) Pipeline 中间产物列表 |
| GET | /api/jobs/{job_id}/artifacts/{file} | (JWT) 下载/查看中间产物 |
| GET | /api/admin/summary | (Auth) 系统汇总：总数/成功率/耗时/token 估算 |
| GET | /api/admin/jobs | (Auth) 任务列表，支持 status/limit/offset 筛选 |
| GET | /api/admin/jobs/{job_id} | (Auth) 任务详情：时间线/token/质量报告（score+status+checks）/错误 |
| GET | /api/admin/queue | (Auth) 队列统计（排队/运行中/完成/失败数、worker 数、Redis 状态）|
| GET | /api/admin/settings | (Auth) 获取系统设置 |
| POST | /api/admin/settings | (Auth) 更新系统设置（支持 desired_worker_count）|
| GET | /api/admin/users | (Auth) 用户列表 + 每人本月用量/成功/失败统计 |
| GET | /api/admin/stats | (Auth) 快速统计：7 天任务数/token、总用户、本月用量 |
| GET | /api/download/{job_id}/html | (JWT) 下载 index.html（S3: 302 → presigned URL）|
| GET | /api/download/{job_id}/standalone | (JWT) 下载 standalone.html |
| GET | /api/download/{job_id}/zip | (JWT) 下载 ZIP 包 |
| GET | /api/admin/jobs/{job_id}/logs | (Auth) 查看/下载日志 |

## 任务状态

| 状态 | 说明 |
|---|---|
| `queued` | 在 Redis 队列中等待，`queue_position` 显示实时排队位置 |
| `running` | Worker 正在生成（5-15 分钟），`worker_name` 显示是哪个 worker |
| `success` | 生成完成，页面显示下载链接 + Pipeline 产物 |
| `failed` | 生成失败，`error_message` 显示原因，可查看 logs.txt |

---

## 操作手册

### 启动（需要 4 个终端）

**终端 1 — Redis：**
```bash
redis-server
```

**终端 2 — Backend API：**
```bash
cd html-ppt-app/backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**终端 3 — Worker Supervisor（默认 2 个 worker）：**
```bash
cd html-ppt-app/backend && python worker_supervisor.py
# 自定义数量：python worker_supervisor.py --count 3
# 或单 worker 模式：python worker.py
```

**终端 4 — Frontend：**
```bash
cd html-ppt-app/frontend
npm run dev -- --host 0.0.0.0
```

打开 http://localhost:5173 → 首次使用需注册账号 → 登录后进入 HTML PPT Studio

管理页面：http://localhost:5173/admin

Admin 密码（可选）：在 `backend/.env` 中设置 `ADMIN_PASSWORD=xxx`，不设置则无密码保护

用户密码在 `backend/.env` 中设置 `JWT_SECRET=xxx`（生产环境务必修改默认值）

### 局域网访问（手机 + 热点）

电脑连接手机热点 → `ipconfig` 查看无线网卡 IPv4 → 手机访问 `http://<IP>:5173`


### 管理页面使用方式

在 backend/.env 中设置 ADMIN_PASSWORD=yourpassword（可选，不设置则无需密码）
启动服务后访问 http://localhost:5173/admin
修改 desired_worker_count 后需重启 worker_supervisor.py

Admin 页面功能：
密码登录（存储于 localStorage）
汇总卡片：总数/成功/失败/运行中/排队/成功率/平均耗时/估算 token/用户数
用量统计卡片：7 天任务数、7 天 token、总用户数、本月总调用、每用户限额
Redis 队列状态显示
Settings 面板：修改 desired_worker_count
用户列表：姓名、email、总任务数、成功/失败、本月次数、限额、注册时间
任务表格：按状态筛选 + 分页 + 用户列 + 质量分数列（颜色标记 pass/warning/fail）
任务详情：时间线、用户信息、token 估算、质量报告（score+status+逐项 checks）、错误信息、下载链接
10 秒自动刷新
---

## Phase 5B — Railway 分离式部署

### 部署架构

```
                         ┌──────────────────────────────────────────┐
  Internet               │  Railway Project "slidehttp"             │
                         │                                          │
  User ───► Frontend     │  Service: backend (API)                  │
  (Vercel/static)        │    uvicorn main:app :8000                │
                         │    ├─ Auth (JWT + bcrypt)                │
                         │    ├─ Job CRUD, rate limiting            │
                         │    └─ Download → presigned S3 URLs       │
                         │                                          │
                         │  Service: worker                         │
                         │    python worker_supervisor.py           │
                         │    ├─ Redis/RQ "generation" 队列         │
                         │    ├─ /tmp/htmlppt-jobs/ 临时目录        │
                         │    ├─ Claude Code + html-ppt-skill       │
                         │    └─ 上传产物到 S3/R2                   │
                         │                                          │
                         │  Plugin: PostgreSQL                      │
                         │    users, jobs, usage_records, settings  │
                         │                                          │
                         │  Plugin: Redis                           │
                         │    RQ queue "generation"                 │
                         │                                          │
                         │  外部: Cloudflare R2 (S3-compatible)     │
                         │    jobs/{job_id}/index.html              │
                         │    jobs/{job_id}/standalone.html         │
                         │    jobs/{job_id}/{job_id}.zip            │
                         │    jobs/{job_id}/logs.txt                │
                         │    jobs/{job_id}/quality_report.json     │
                         └──────────────────────────────────────────┘
```

### 两种模式

| 模式 | STORAGE_PROVIDER | 数据库 | 文件存储 | 适用场景 |
|---|---|---|---|---|
| 本地开发 | `local` | SQLite | 本地 outputs/ 目录 | 4 终端本地开发 |
| Railway 生产 | `s3` | PostgreSQL | S3/R2 对象存储 | Railway 公网部署 |

### 关键文件

```
Dockerfile                          Python 3.12 + Node.js 18 + Claude Code CLI
railway.toml                        显式指定 DOCKERFILE builder（避免自动检测问题）
.env.example                        本地开发环境变量模板
.env.production.example             生产环境变量模板
deploy/RAILWAY.md                   详细部署指南（10 步）
scripts/smoke_test_remote.py        Phase 5B 远程冒烟测试
scripts/worker_health_check.py      Worker 健康检查
services/storage/storage_client.py  存储抽象层（Local + S3）
```

### 核心变化（相比 Phase 5A）

| 方面 | Phase 5A | Phase 5B |
|---|---|---|
| 数据库 | SQLite on Volume | PostgreSQL plugin |
| 文件存储 | Volume /data/outputs | S3/R2 对象存储 |
| 下载 | 公开 FileResponse | JWT + presigned URL |
| 预览 | /outputs/ 静态挂载 | /api/preview/{id} + JWT |
| Volume | 需要 | 不需要 |
| Backend-Worker | 共享 Volume 读文件 | 通过 S3/Database 通信 |

---

## Phase 5C — 生产 Bug 修复 & 部署踩坑

### 修复 1：download_token 机制（`<a>` 标签下载认证）

**问题**：Phase 5B 下载/预览路由加了 JWT 认证，但浏览器 `<a href>` 点击下载时不会发送 `Authorization` header，导致 401。

**解决**：后端在创建 job 时生成 `secrets.token_urlsafe(16)` 随机令牌，存入 `jobs.download_token`，直接嵌入 API 返回的所有下载/预览 URL（`?token=xxx`）。服务端验证时接受 token 或 JWT，token 优先，无需前端改动。

涉及文件：`models.py`（新增 `download_token` 列 + URL 嵌入）、`database.py`（迁移 + 旧任务补填）、`main.py`（`_auth_download()` 验证逻辑）

### 修复 2：消除 `_bearer` 前向引用

**问题**：`main.py` 中 `_bearer = HTTPBearer(auto_error=False)` 定义在 `_get_optional_user()` 之后，Python 函数定义时求值默认参数导致 `NameError`。

**解决**：彻底删除 `_bearer` 和 `HTTPBearer` 依赖，改用 FastAPI 内置 `Header(None)` 直接读取 `Authorization` 头，新建 `_extract_token()` 函数。零模块级变量依赖，彻底避免定义顺序问题。

涉及文件：`main.py`（`_extract_token` 替代 `_bearer`，`_get_optional_user` + `get_current_user` 改用新依赖）

### Railway 部署踩坑总集

| # | 故障 | 根因 | 解决 |
|---|---|---|---|
| 1 | Frontend 403 Forbidden | Vite 6 `allowedHosts: true` bug | 降级 Vite 5.4.21 |
| 2 | Frontend 502 Bad Gateway | Root Directory 设成 backend 路径 | 改为 `html-ppt-app/frontend` |
| 3 | 下载 401 认证失败 | `<a>` 标签不传 Authorization header | download_token 嵌 URL |
| 4 | `_bearer` NameError | Python 前向引用 + 旧快照 | `_extract_token` + 删服务重建 |
| 5 | **Railway 代码快照卡死** | Railway 内部快照永不更新，Disconnect/Reconnect 无效 | **删服务重建** |
| 6 | 相对 URL 下载失败 | API 返回 `/api/download/...` 相对路径 | `public_backend_url` 拼绝对 URL |

### Railway 快照卡死 — 诊断 & 处理

**症状**：代码已推到 GitHub，反复部署但构建日志永不变化（步骤数不变、CACHEBUST 不变、DIAG 诊断不出现）。

**诊断**：WebFetch 验证 GitHub 代码正确 → `git ls-remote` 验证远程 HEAD 最新 → Dockerfile 加 `RUN grep` 诊断 → 日志不出现 → 确认快照卡死。

**处理**：Disconnect/Reconnect GitHub（无效）→ **删除服务重建**（数据库是独立 Plugin，数据不丢）→ 构建步骤从 `[1/17]` 变为 `[1/20]`，CACHEBUST 从 9 变 10。

### 后续部署流程

正常：改代码 → `git push` → Railway 自动/手动 Deploy → 生效

快照又卡死：直接删服务重建，5 分钟搞定。不要折腾 Disconnect/Reconnect。

---

## 每任务输出文件

```
local: outputs/{job_id}/
S3:   s3://{bucket}/jobs/{job_id}/

  prompt.txt             发送给 Claude Code 的 prompt
  generation_prompt.txt  （长文本模式）含 deck plan + 上下文的完整 prompt
  input_cleaned.json     （长文本模式）清洗后的结构化数据
  deck_plan.json         （长文本模式）每页规划
  packed_context.json    （长文本模式）每页原文片段
  quality_report.json    质量报告（所有模式均生成；长文本模式含全量检查）
  index.html             生成的 PPT
  standalone.html        独立版本（可离线打开）
  logs.txt               Worker 运行日志
```
