// ── Auth (Phase 4G) ────────────────────────────────────────────────────

const TOKEN_KEY = 'slidehttp_token';
const USER_KEY = 'slidehttp_user';

// In production (Railway), the backend is on a separate domain.
// Set VITE_API_BASE_URL on Railway to e.g. https://backend-production-e8475.up.railway.app
const BASE = (import.meta as any).env?.VITE_API_BASE_URL || '';

function apiUrl(path: string): string {
  return BASE + path;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function authDownloadUrl(url: string | null | undefined): string {
  if (!url) return '';
  const token = getToken();
  if (!token) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}access_token=${token}`;
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getSavedUser(): { id: string; name: string; email: string } | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function setSavedUser(user: { id: string; name: string; email: string }): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface UserInfo {
  id: string;
  name: string;
  email: string;
  created_at?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: UserInfo;
}

export async function authRegister(name: string, email: string, password: string, inviteCode?: string): Promise<void> {
  const res = await fetch(apiUrl('/api/auth/register'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, password, invite_code: inviteCode || undefined }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || 'Registration failed');
  }
}

export async function authLogin(email: string, password: string): Promise<LoginResponse> {
  const res = await fetch(apiUrl('/api/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || 'Login failed');
  }
  const data: LoginResponse = await res.json();
  setToken(data.access_token);
  setSavedUser(data.user);
  return data;
}

export async function authMe(): Promise<UserInfo> {
  const res = await fetch(apiUrl('/api/auth/me'), { headers: authHeaders() });
  if (!res.ok) {
    throw new Error('Not authenticated');
  }
  return res.json();
}

export async function authLogout(): Promise<void> {
  await fetch(apiUrl('/api/auth/logout'), { method: 'POST', headers: authHeaders() });
  clearToken();
}

// ── Job generation ───────────────────────────────────────────────────────

export interface GenerateRequest {
  topic: string;
  content: string;
  language: string;
  style: string;
  slide_count: number;
  audience: string;
  extra_requirements: string;
  search_level: string; // "none" | "light" | "deep"
  model: string; // "deepseek-v4-pro" | "deepseek-v4-flash"
}

export interface CreateJobResponse {
  job_id: string;
  status: string;
  remaining_generations: number;
}

export interface JobResponse {
  job_id: string;
  status: string; // "queued" | "running" | "success" | "failed"
  topic?: string;
  language?: string;
  style?: string;
  slide_count?: number;
  content_chars?: number;
  error_message?: string;
  // Output URLs (only present when status == "success")
  preview_url?: string;
  preview_standalone_url?: string;
  download_html_url?: string;
  download_standalone_url?: string;
  download_zip_url?: string;
  logs_url?: string;
  // Worker / queue info
  worker_name?: string | null;
  queue_position?: number | null;
  // Timestamps
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  // Quality check (Phase 4E)
  quality_status?: string; // "pass" | "warning" | "fail"
  quality_score?: number;  // 0-100
}

export interface JobListResponse {
  jobs: JobResponse[];
}

export async function createJob(req: GenerateRequest): Promise<CreateJobResponse> {
  const res = await fetch(apiUrl("/api/jobs"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `Request failed with status ${res.status}`);
  }

  return res.json();
}

export async function getJob(jobId: string): Promise<JobResponse> {
  const res = await fetch(apiUrl(`/api/jobs/${jobId}`));
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `Request failed with status ${res.status}`);
  }
  return res.json();
}

export async function listJobs(limit: number = 20): Promise<JobListResponse> {
  const res = await fetch(apiUrl(`/api/jobs?limit=${limit}`));
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `Request failed with status ${res.status}`);
  }
  return res.json();
}

// ── Pipeline artifacts ─────────────────────────────────────────────

export interface ArtifactInfo {
  filename: string;
  size: number;
  url: string;
}

export interface ArtifactsResponse {
  job_id: string;
  artifacts: ArtifactInfo[];
}

export async function getArtifacts(jobId: string): Promise<ArtifactsResponse> {
  const res = await fetch(apiUrl(`/api/jobs/${jobId}/artifacts`));
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `Request failed with status ${res.status}`);
  }
  return res.json();
}

// ── Admin API (Phase 4C) ─────────────────────────────────────────────

function adminHeaders(password: string): Record<string, string> {
  return { 'X-Admin-Password': password };
}

export interface AdminSummary {
  total_jobs: number;
  success_jobs: number;
  failed_jobs: number;
  running_jobs: number;
  queued_jobs: number;
  total_users: number;
  total_content_chars: number;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  average_generation_seconds: number;
  success_rate: number;
  // Phase 5H
  path_check_failed_jobs: number;
  missing_storage_object_jobs: number;
}

export interface AdminJobItem {
  job_id: string;
  status: string;
  user_name?: string;
  user_email?: string;
  topic?: string;
  language?: string;
  style?: string;
  audience?: string;
  slide_count?: number;
  content_chars?: number;
  estimated_input_tokens?: number;
  estimated_output_tokens?: number;
  quality_status?: string;
  quality_score?: number;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  error_message?: string;
}

export interface AdminJobList {
  jobs: AdminJobItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminJobDetail {
  job_id: string;
  status: string;
  user_name?: string;
  user_email?: string;
  topic?: string;
  content?: string;
  language?: string;
  style?: string;
  audience?: string;
  slide_count?: number;
  content_chars?: number;
  extra_requirements?: string;
  search_level?: string;
  worker_name?: string;
  model_name?: string;
  estimated_input_tokens?: number;
  estimated_output_tokens?: number;
  generation_prompt_chars?: number;
  generated_html_chars?: number;
  error_message?: string;
  output_dir?: string;
  prompt_path?: string;
  logs_path?: string;
  index_html_path?: string;
  standalone_html_path?: string;
  zip_path?: string;
  quality_report?: Record<string, any>;
  quality_status?: string;
  quality_score?: number;
  quality_warnings_count?: number;
  quality_errors_count?: number;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  queue_seconds?: number;
  generation_seconds?: number;
  preview_url?: string;
  preview_standalone_url?: string;
  download_html_url?: string;
  download_standalone_url?: string;
  download_zip_url?: string;
  logs_url?: string;
  // Phase 5H: Path check
  path_check_status?: string;
  path_check_errors_count: number;
  path_check_warnings_count: number;
  path_check_key?: string;
  // Storage keys (Phase 5B)
  index_html_key?: string;
  standalone_html_key?: string;
  zip_key?: string;
  logs_key?: string;
  quality_report_key?: string;
  deck_plan_key?: string;
  packed_context_key?: string;
  input_cleaned_key?: string;
  generation_prompt_key?: string;
}

export interface AdminQueue {
  queued_jobs: number;
  started_jobs: number;
  finished_jobs: number;
  failed_jobs: number;
  worker_count_detected: number;
  worker_names: string[];
  redis_connected: boolean;
  rq_queue_length: number;
}

export interface SettingItem {
  key: string;
  value?: string;
}

// ── Admin user / stats (Phase 4F) ───────────────────────────────────

export interface AdminUserItem {
  user_id: string;
  name: string;
  email: string;
  is_admin: boolean;
  can_generate: boolean;
  created_at?: string;
  total_jobs: number;
  success_jobs: number;
  failed_jobs: number;
  this_month_count: number;
  monthly_limit: number;
}

export interface AdminUserList {
  users: AdminUserItem[];
  total: number;
}

export interface AdminStats {
  last_7_days_jobs: number;
  last_7_days_tokens: number;
  total_users: number;
  total_usage_this_month: number;
  free_limit: number;
}

async function adminFetch(path: string, password: string, init?: RequestInit) {
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: { ...(init?.headers || {}), ...adminHeaders(password) },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `Admin API error: ${res.status}`);
  }
  return res.json();
}

export async function adminGetSummary(password: string): Promise<AdminSummary> {
  return adminFetch('/api/admin/summary', password);
}

export async function adminListJobs(
  password: string,
  status?: string,
  limit?: number,
  offset?: number,
): Promise<AdminJobList> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (limit) params.set('limit', String(limit));
  if (offset) params.set('offset', String(offset));
  return adminFetch(`/api/admin/jobs?${params}`, password);
}

export async function adminGetJobDetail(jobId: string, password: string): Promise<AdminJobDetail> {
  return adminFetch(`/api/admin/jobs/${jobId}`, password);
}

export async function adminGetQueue(password: string): Promise<AdminQueue> {
  return adminFetch('/api/admin/queue', password);
}

export async function adminGetSettings(password: string): Promise<SettingItem[]> {
  return adminFetch('/api/admin/settings', password);
}

export async function adminSetSetting(key: string, value: string, password: string): Promise<void> {
  await adminFetch('/api/admin/settings', password, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, value }),
  });
}

export async function adminGetUsers(password: string): Promise<AdminUserList> {
  return adminFetch('/api/admin/users', password);
}

export async function adminUpdateUser(
  userId: string,
  body: { is_admin?: boolean; can_generate?: boolean },
  password: string,
): Promise<{ user_id: string; is_admin: boolean; can_generate: boolean }> {
  return adminFetch(`/api/admin/users/${userId}`, password, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function adminGetStats(password: string): Promise<AdminStats> {
  return adminFetch('/api/admin/stats', password);
}


// ── Admin invite codes (Phase 5D) ────────────────────────────────────

export interface InviteCodeItem {
  id: string;
  code: string;
  created_by?: string;
  bound_user_id?: string;
  bound_user_name?: string;
  bound_user_email?: string;
  monthly_limit: number;
  is_active: boolean;
  created_at?: string;
  bound_at?: string;
  notes?: string;
}

export async function adminListInviteCodes(password: string): Promise<{ invite_codes: InviteCodeItem[]; total: number }> {
  return adminFetch('/api/admin/invite-codes', password);
}

export async function adminCreateInviteCode(
  code: string,
  monthlyLimit: number,
  notes: string,
  password: string,
): Promise<any> {
  return adminFetch('/api/admin/invite-codes', password, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, monthly_limit: monthlyLimit, notes }),
  });
}

export async function adminUpdateInviteCode(
  inviteId: string,
  body: { is_active?: boolean; monthly_limit?: number; notes?: string },
  password: string,
): Promise<any> {
  return adminFetch(`/api/admin/invite-codes/${inviteId}`, password, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function adminDeleteInviteCode(inviteId: string, password: string): Promise<void> {
  return adminFetch(`/api/admin/invite-codes/${inviteId}`, password, {
    method: 'DELETE',
  });
}

// ── My Jobs / My Usage (Phase 4G) ────────────────────────────────────

export interface MyJobItem {
  job_id: string;
  status: string;
  topic?: string;
  created_at?: string;
  quality_status?: string;
  quality_score?: number;
  preview_url?: string;
  download_html_url?: string;
  download_standalone_url?: string;
  download_zip_url?: string;
}

export interface MyUsageResponse {
  month: string;
  used: number;
  limit: number;
  remaining: number;
  success_jobs: number;
  failed_jobs: number;
}

export async function myJobs(): Promise<{ jobs: MyJobItem[] }> {
  const res = await fetch(apiUrl('/api/my/jobs'), { headers: authHeaders() });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || 'Failed to fetch jobs');
  }
  return res.json();
}

export async function myUsage(): Promise<MyUsageResponse> {
  const res = await fetch(apiUrl('/api/my/usage'), { headers: authHeaders() });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || 'Failed to fetch usage');
  }
  return res.json();
}


// ── Feedback (Phase 5E) ────────────────────────────────────────────────

export interface FeedbackRequest {
  rating: number;
  content_accuracy: number;
  visual_quality: number;
  usefulness: number;
  would_use_again: boolean;
  most_needed_feature?: string;
  comment?: string;
}

export interface FeedbackResponse {
  id: string;
  job_id: string;
  rating: number;
  content_accuracy: number;
  visual_quality: number;
  usefulness: number;
  would_use_again: boolean;
  most_needed_feature?: string;
  comment?: string;
  created_at?: string;
}

export async function submitFeedback(jobId: string, req: FeedbackRequest): Promise<FeedbackResponse> {
  const res = await fetch(apiUrl(`/api/jobs/${jobId}/feedback`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || 'Failed to submit feedback');
  }
  return res.json();
}

export async function getFeedback(jobId: string): Promise<FeedbackResponse> {
  const res = await fetch(apiUrl(`/api/jobs/${jobId}/feedback`), { headers: authHeaders() });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || 'Failed to get feedback');
  }
  return res.json();
}


// ── CSV Export (Phase 5E) ──────────────────────────────────────────────

export function adminExportUrl(type: 'jobs' | 'users' | 'feedback', password: string): string {
  const base = apiUrl(`/api/admin/export/${type}.csv`);
  // CSV export uses X-Admin-Password header — but <a> tags can't set headers.
  // Use a query param workaround via backend redirect.
  return `${base}?admin_password=${encodeURIComponent(password)}`;
}
