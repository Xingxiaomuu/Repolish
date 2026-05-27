import { useState, useEffect, useCallback } from 'react';
import {
  adminGetSummary, adminListJobs, adminGetJobDetail, adminGetQueue,
  adminGetSettings, adminSetSetting, adminGetUsers, adminGetStats,
  adminUpdateUser, authDownloadUrl,
  type AdminSummary, type AdminJobItem, type AdminJobDetail,
  type AdminQueue, type SettingItem, type AdminUserItem, type AdminStats,
} from './api';

const STATUS_OPTIONS = ['', 'queued', 'running', 'success', 'failed'];

export default function AdminPage() {
  // Auth
  const [password, setPassword] = useState(() => localStorage.getItem('admin_password') || '');
  const [pwInput, setPwInput] = useState(password);
  const [authError, setAuthError] = useState('');

  // Data
  const [summary, setSummary] = useState<AdminSummary | null>(null);
  const [jobs, setJobs] = useState<AdminJobItem[]>([]);
  const [jobTotal, setJobTotal] = useState(0);
  const [queue, setQueue] = useState<AdminQueue | null>(null);
  const [allSettings, setAllSettings] = useState<SettingItem[]>([]);
  const [users, setUsers] = useState<AdminUserItem[]>([]);
  const [stats, setStats] = useState<AdminStats | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 20;

  // Detail
  const [detail, setDetail] = useState<AdminJobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Settings
  const [workerCountInput, setWorkerCountInput] = useState('');
  const [settingsSaving, setSettingsSaving] = useState(false);

  // Loading
  const [loading, setLoading] = useState(false);

  const doLogin = useCallback(() => {
    localStorage.setItem('admin_password', pwInput);
    setPassword(pwInput);
    setAuthError('');
  }, [pwInput]);

  const doLogout = useCallback(() => {
    localStorage.removeItem('admin_password');
    setPassword('');
    setPwInput('');
    setSummary(null);
    setJobs([]);
    setQueue(null);
    setDetail(null);
  }, []);

  const fetchAll = useCallback(async () => {
    if (!password) return;
    setLoading(true);
    setAuthError('');
    try {
      const [s, jl, q, st, us, xs] = await Promise.all([
        adminGetSummary(password),
        adminListJobs(password, statusFilter || undefined, PAGE_SIZE, page * PAGE_SIZE),
        adminGetQueue(password),
        adminGetSettings(password),
        adminGetUsers(password),
        adminGetStats(password),
      ]);
      setSummary(s);
      setJobs(jl.jobs);
      setJobTotal(jl.total);
      setQueue(q);
      setAllSettings(st);
      setUsers(us.users);
      setStats(xs);

      // Load worker count from settings
      const wc = st.find((s: SettingItem) => s.key === 'desired_worker_count');
      if (wc && wc.value) setWorkerCountInput(wc.value);
    } catch (err: any) {
      if (err.message?.includes('401') || err.message?.includes('Invalid')) {
        setAuthError('Invalid password');
        setPassword('');
        localStorage.removeItem('admin_password');
      }
    } finally {
      setLoading(false);
    }
  }, [password, statusFilter, page]);

  useEffect(() => {
    if (password) fetchAll();
  }, [fetchAll, password]);

  // Poll every 10s
  useEffect(() => {
    if (!password) return;
    const iv = setInterval(fetchAll, 10000);
    return () => clearInterval(iv);
  }, [fetchAll, password]);

  const openDetail = async (jobId: string) => {
    setDetailLoading(true);
    setDetail(null);
    try {
      const d = await adminGetJobDetail(jobId, password);
      setDetail(d);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const saveWorkerCount = async () => {
    if (!password) return;
    setSettingsSaving(true);
    try {
      await adminSetSetting('desired_worker_count', workerCountInput, password);
      setAllSettings(prev => {
        const rest = prev.filter(s => s.key !== 'desired_worker_count');
        return [...rest, { key: 'desired_worker_count', value: workerCountInput }];
      });
    } catch (err: any) {
      alert('Failed to save: ' + (err.message || 'Unknown error'));
    } finally {
      setSettingsSaving(false);
    }
  };

  const toggleUserAdmin = async (userId: string, current: boolean) => {
    if (!password) return;
    try {
      const res = await adminUpdateUser(userId, { is_admin: !current }, password);
      setUsers(prev => prev.map(u =>
        u.user_id === userId ? { ...u, is_admin: res.is_admin } : u
      ));
    } catch (err: any) {
      alert('Failed: ' + (err.message || 'Unknown error'));
    }
  };

  const toggleUserGenerate = async (userId: string, current: boolean) => {
    if (!password) return;
    try {
      const res = await adminUpdateUser(userId, { can_generate: !current }, password);
      setUsers(prev => prev.map(u =>
        u.user_id === userId ? { ...u, can_generate: res.can_generate } : u
      ));
    } catch (err: any) {
      alert('Failed: ' + (err.message || 'Unknown error'));
    }
  };

  const formatTime = (s?: string) => {
    if (!s) return '-';
    return new Date(s).toLocaleString();
  };

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      queued: '#f59e0b', running: '#3b82f6', success: '#22c55e', failed: '#ef4444',
    };
    return (
      <span style={{
        display: 'inline-block', padding: '0.15rem 0.5rem', borderRadius: '12px',
        fontSize: '0.78rem', fontWeight: 600, color: '#fff',
        backgroundColor: colors[status] || '#888',
      }}>
        {status}
      </span>
    );
  };

  if (!password) {
    return (
      <div className="container">
        <header>
          <h1>Admin Dashboard</h1>
        </header>
        <div style={{ maxWidth: 360, margin: '3rem auto' }}>
          <label htmlFor="admin-pw">Enter admin password</label>
          <input
            id="admin-pw"
            type="password"
            value={pwInput}
            onChange={e => setPwInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && doLogin()}
            placeholder="Admin password"
            style={{ width: '100%', marginTop: '0.4rem' }}
          />
          <button
            onClick={doLogin}
            style={{ marginTop: '0.75rem', width: '100%' }}
            className="generate-btn"
          >
            Login
          </button>
          {authError && <p style={{ color: '#ef4444', marginTop: '0.5rem', fontSize: '0.85rem' }}>{authError}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="container admin-container" style={{ maxWidth: 1200 }}>
      {/* Header */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>Admin Dashboard</h1>
          <p className="subtitle">System monitoring &amp; management</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <a href="/" style={{ fontSize: '0.85rem', color: '#5b8def' }}>Back to App</a>
          <button onClick={doLogout} className="preset-btn" style={{ fontSize: '0.8rem' }}>Logout</button>
        </div>
      </header>

      {/* Summary Cards */}
      {summary && (
        <div className="admin-cards">
          <div className="admin-card"><strong>{summary.total_jobs}</strong><span>Total Jobs</span></div>
          <div className="admin-card green"><strong>{summary.success_jobs}</strong><span>Success</span></div>
          <div className="admin-card red"><strong>{summary.failed_jobs}</strong><span>Failed</span></div>
          <div className="admin-card blue"><strong>{summary.running_jobs}</strong><span>Running</span></div>
          <div className="admin-card yellow"><strong>{summary.queued_jobs}</strong><span>Queued</span></div>
          <div className="admin-card"><strong>{(summary.success_rate * 100).toFixed(1)}%</strong><span>Success Rate</span></div>
          <div className="admin-card"><strong>{summary.average_generation_seconds.toFixed(0)}s</strong><span>Avg Gen Time</span></div>
          <div className="admin-card"><strong>{(summary.estimated_input_tokens + summary.estimated_output_tokens).toLocaleString()}</strong><span>Est. Total Tokens</span></div>
        </div>
      )}

      {/* Queue Status */}
      {queue && (
        <div className="admin-section">
          <h3>Queue Status</h3>
          <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', fontSize: '0.9rem' }}>
            <span>Redis: <strong style={{ color: queue.redis_connected ? '#22c55e' : '#ef4444' }}>{queue.redis_connected ? 'Connected' : 'Disconnected'}</strong></span>
            <span>RQ Queue Length: <strong>{queue.rq_queue_length}</strong></span>
            <span>Workers: <strong>{queue.worker_count_detected}</strong> {queue.worker_names.length > 0 && `(${queue.worker_names.join(', ')})`}</span>
          </div>
        </div>
      )}

      {/* Stats (Phase 4F) */}
      {stats && (
        <div className="admin-section">
          <h3>Usage Stats</h3>
          <div className="admin-cards" style={{ marginBottom: 0 }}>
            <div className="admin-card"><strong>{stats.last_7_days_jobs}</strong><span>7-Day Jobs</span></div>
            <div className="admin-card"><strong>{stats.last_7_days_tokens.toLocaleString()}</strong><span>7-Day Tokens</span></div>
            <div className="admin-card"><strong>{stats.total_users}</strong><span>Total Users</span></div>
            <div className="admin-card"><strong>{stats.total_usage_this_month}</strong><span>Month Usage</span></div>
            <div className="admin-card"><strong>{stats.free_limit}</strong><span>Free Limit/User</span></div>
          </div>
        </div>
      )}

      {/* Users (Phase 4F/4G) */}
      {users.length > 0 && (
        <div className="admin-section">
          <h3>Users ({users.length})</h3>
          <div style={{ overflowX: 'auto' }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Admin</th>
                  <th>Generate</th>
                  <th>Total Jobs</th>
                  <th>Success</th>
                  <th>Failed</th>
                  <th>This Month</th>
                  <th>Limit</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <tr key={u.user_id}>
                    <td>{u.name}</td>
                    <td className="ellipsis">{u.email}</td>
                    <td>
                      <button
                        className="preset-btn"
                        style={{
                          fontSize: '0.72rem', padding: '0.2rem 0.5rem',
                          background: u.is_admin ? '#22c55e' : '#e2e8f0',
                          color: u.is_admin ? '#fff' : '#64748b',
                          borderColor: u.is_admin ? '#22c55e' : '#e2e8f0',
                          borderRadius: 4,
                        }}
                        onClick={() => toggleUserAdmin(u.user_id, u.is_admin)}
                      >
                        {u.is_admin ? 'Yes' : 'No'}
                      </button>
                    </td>
                    <td>
                      <button
                        className="preset-btn"
                        style={{
                          fontSize: '0.72rem', padding: '0.2rem 0.5rem',
                          background: u.can_generate ? '#22c55e' : '#ef4444',
                          color: '#fff',
                          borderColor: u.can_generate ? '#22c55e' : '#ef4444',
                          borderRadius: 4,
                        }}
                        onClick={() => toggleUserGenerate(u.user_id, u.can_generate)}
                      >
                        {u.can_generate ? 'Yes' : 'No'}
                      </button>
                    </td>
                    <td className="num">{u.total_jobs}</td>
                    <td className="num" style={{color: '#22c55e'}}>{u.success_jobs}</td>
                    <td className="num" style={{color: u.failed_jobs > 0 ? '#ef4444' : undefined}}>{u.failed_jobs}</td>
                    <td className="num" style={{fontWeight:600, color: u.this_month_count >= u.monthly_limit ? '#ef4444' : '#f59e0b'}}>{u.this_month_count}</td>
                    <td className="num">{u.monthly_limit}</td>
                    <td>{u.created_at ? new Date(u.created_at).toLocaleDateString() : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Settings */}
      <div className="admin-section">
        <h3>Settings</h3>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ fontWeight: 500, fontSize: '0.9rem' }}>Worker Count:</label>
          <input
            type="number"
            min={1}
            max={8}
            value={workerCountInput}
            onChange={e => setWorkerCountInput(e.target.value)}
            style={{ width: 80 }}
          />
          <button onClick={saveWorkerCount} disabled={settingsSaving} className="preset-btn active" style={{ borderRadius: 8 }}>
            {settingsSaving ? 'Saving...' : 'Save'}
          </button>
          <span style={{ fontSize: '0.75rem', color: '#888' }}>(requires supervisor restart)</span>
        </div>
      </div>

      {/* Job Table */}
      <div className="admin-section">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
          <h3 style={{ margin: 0 }}>Jobs</h3>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            {STATUS_OPTIONS.map(s => (
              <button
                key={s || 'all'}
                className={`preset-btn ${statusFilter === s ? 'active' : ''}`}
                onClick={() => { setStatusFilter(s); setPage(0); }}
                style={{ fontSize: '0.8rem', padding: '0.3rem 0.65rem' }}
              >
                {s || 'All'}
              </button>
            ))}
          </div>
        </div>

        <div style={{ overflowX: 'auto', marginTop: '0.75rem' }}>
          <table className="admin-table">
            <thead>
              <tr>
                <th>Job ID</th>
                <th>User</th>
                <th>Status</th>
                <th>Topic</th>
                <th>Lang</th>
                <th>Style</th>
                <th>Slides</th>
                <th>Chars</th>
                <th>Tokens In</th>
                <th>Tokens Out</th>
                <th>Quality</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(j => (
                <tr key={j.job_id} className={detail?.job_id === j.job_id ? 'selected-row' : ''}>
                  <td className="mono" title={j.job_id}>{j.job_id.slice(-8)}</td>
                  <td className="ellipsis" title={j.user_email || ''}>{j.user_name || '-'}</td>
                  <td>{statusBadge(j.status)}</td>
                  <td className="ellipsis" title={j.topic}>{j.topic?.slice(0, 40) || '-'}</td>
                  <td>{j.language || '-'}</td>
                  <td>{j.style || '-'}</td>
                  <td className="num">{j.slide_count ?? '-'}</td>
                  <td className="num">{j.content_chars?.toLocaleString() ?? '-'}</td>
                  <td className="num">{j.estimated_input_tokens?.toLocaleString() ?? '-'}</td>
                  <td className="num">{j.estimated_output_tokens?.toLocaleString() ?? '-'}</td>
                  <td className="num">{j.quality_score != null ? <span style={{fontWeight:600, color: j.quality_status==='pass'?'#22c55e':j.quality_status==='fail'?'#ef4444':'#f59e0b'}}>{j.quality_score}</span> : '-'}</td>
                  <td>{j.created_at ? formatTime(j.created_at) : '-'}</td>
                  <td>
                    <button className="preset-btn" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                      onClick={() => openDetail(j.job_id)}>
                      Detail
                    </button>
                  </td>
                </tr>
              ))}
              {jobs.length === 0 && (
                <tr><td colSpan={13} style={{ textAlign: 'center', color: '#888', padding: '2rem' }}>No jobs found</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {jobTotal > PAGE_SIZE && (
          <div style={{ display: 'flex', justifyContent: 'center', gap: '0.5rem', marginTop: '0.75rem', alignItems: 'center' }}>
            <button className="preset-btn" disabled={page === 0} onClick={() => setPage(p => p - 1)}>Prev</button>
            <span style={{ fontSize: '0.85rem' }}>
              Page {page + 1} of {Math.ceil(jobTotal / PAGE_SIZE)} ({jobTotal} total)
            </span>
            <button className="preset-btn" disabled={(page + 1) * PAGE_SIZE >= jobTotal} onClick={() => setPage(p => p + 1)}>Next</button>
          </div>
        )}
      </div>

      {/* Job Detail Panel */}
      {detailLoading && (
        <div className="admin-section">
          <p style={{ color: '#888' }}>Loading job detail...</p>
        </div>
      )}

      {detail && (
        <div className="admin-section detail-panel">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
            <h3 style={{ margin: 0 }}>Job Detail — {detail.job_id}</h3>
            <button className="preset-btn" onClick={() => setDetail(null)}>Close</button>
          </div>

          <div className="detail-grid">
            <div className="detail-group">
              <h4>Info</h4>
              <table className="kv-table">
                <tbody>
                  <tr><td>Status</td><td>{statusBadge(detail.status)}</td></tr>
                  <tr><td>Topic</td><td>{detail.topic || '-'}</td></tr>
                  <tr><td>Language</td><td>{detail.language || '-'}</td></tr>
                  <tr><td>Style</td><td>{detail.style || '-'}</td></tr>
                  <tr><td>Audience</td><td>{detail.audience || '-'}</td></tr>
                  <tr><td>Slide Count</td><td>{detail.slide_count ?? '-'}</td></tr>
                  <tr><td>Content Chars</td><td>{detail.content_chars?.toLocaleString() ?? '-'}</td></tr>
                  <tr><td>Search Level</td><td>{detail.search_level || '-'}</td></tr>
                  <tr><td>Worker</td><td>{detail.worker_name || '-'}</td></tr>
                  <tr><td>Model</td><td>{detail.model_name || '-'}</td></tr>
                </tbody>
              </table>
            </div>

            <div className="detail-group">
              <h4>Timing</h4>
              <table className="kv-table">
                <tbody>
                  <tr><td>Created</td><td>{formatTime(detail.created_at)}</td></tr>
                  <tr><td>Started</td><td>{formatTime(detail.started_at)}</td></tr>
                  <tr><td>Finished</td><td>{formatTime(detail.finished_at)}</td></tr>
                  <tr><td>Queue Wait</td><td>{detail.queue_seconds != null ? `${detail.queue_seconds}s` : '-'}</td></tr>
                  <tr><td>Generation</td><td>{detail.generation_seconds != null ? `${detail.generation_seconds}s` : '-'}</td></tr>
                </tbody>
              </table>
            </div>

            <div className="detail-group">
              <h4>Token Estimation</h4>
              <table className="kv-table">
                <tbody>
                  <tr><td>Prompt Chars</td><td>{detail.generation_prompt_chars?.toLocaleString() ?? '-'}</td></tr>
                  <tr><td>Est. Input Tokens</td><td>{detail.estimated_input_tokens?.toLocaleString() ?? '-'}</td></tr>
                  <tr><td>HTML Chars</td><td>{detail.generated_html_chars?.toLocaleString() ?? '-'}</td></tr>
                  <tr><td>Est. Output Tokens</td><td>{detail.estimated_output_tokens?.toLocaleString() ?? '-'}</td></tr>
                </tbody>
              </table>
            </div>

            {(detail.preview_url || detail.download_html_url) && (
              <div className="detail-group">
                <h4>Download Links</h4>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.3rem' }}>
                  {detail.preview_url && <a href={authDownloadUrl(detail.preview_url)} target="_blank" rel="noopener noreferrer" className="result-link" style={{ fontSize: '0.8rem' }}>Preview</a>}
                  {detail.preview_standalone_url && <a href={authDownloadUrl(detail.preview_standalone_url)} target="_blank" rel="noopener noreferrer" className="result-link accent" style={{ fontSize: '0.8rem' }}>Standalone</a>}
                  {detail.download_html_url && <a href={authDownloadUrl(detail.download_html_url)} className="result-link" style={{ fontSize: '0.8rem' }}>HTML</a>}
                  {detail.download_standalone_url && <a href={authDownloadUrl(detail.download_standalone_url)} className="result-link accent" style={{ fontSize: '0.8rem' }}>Standalone DL</a>}
                  {detail.download_zip_url && <a href={authDownloadUrl(detail.download_zip_url)} className="result-link" style={{ fontSize: '0.8rem' }}>ZIP</a>}
                  {detail.logs_url && <a href={authDownloadUrl(detail.logs_url)} target="_blank" rel="noopener noreferrer" className="result-link" style={{ fontSize: '0.8rem' }}>Logs</a>}
                </div>
              </div>
            )}
          </div>

          {detail.error_message && (
            <div style={{ marginTop: '0.75rem' }}>
              <h4 style={{ color: '#ef4444' }}>Error</h4>
              <pre className="error-detail">{detail.error_message}</pre>
            </div>
          )}

          {detail.quality_status && (
            <div style={{ marginTop: '0.75rem' }}>
              <h4>Quality Report</h4>
              <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                <span>Status: <strong style={{
                  color: detail.quality_status === 'pass' ? '#22c55e' : detail.quality_status === 'fail' ? '#ef4444' : '#f59e0b'
                }}>{detail.quality_status.toUpperCase()}</strong></span>
                <span>Score: <strong>{detail.quality_score ?? '-'}/100</strong></span>
                <span>Warnings: <strong style={{color: '#f59e0b'}}>{detail.quality_warnings_count ?? 0}</strong></span>
                <span>Errors: <strong style={{color: '#ef4444'}}>{detail.quality_errors_count ?? 0}</strong></span>
              </div>
              {detail.quality_report?.checks && (
                <div style={{ maxHeight: 300, overflowY: 'auto', background: '#1a1a2e', borderRadius: 8, padding: '0.5rem 0.75rem' }}>
                  {detail.quality_report.checks.map((c: any, i: number) => {
                    const icon = c.result === 'PASS' ? '✓' : c.result === 'WARN' ? '⚠' : '✗';
                    const color = c.result === 'PASS' ? '#22c55e' : c.result === 'WARN' ? '#f59e0b' : '#ef4444';
                    return (
                      <div key={i} style={{ fontSize: '0.8rem', padding: '0.15rem 0', fontFamily: 'monospace' }}>
                        <span style={{ color }}>[{icon}]</span>{' '}
                        <span style={{ color: '#aaa' }}>{c.name}:</span>{' '}
                        <span style={{ color: '#ddd' }}>{c.message}</span>
                      </div>
                    );
                  })}
                </div>
              )}
              {detail.quality_report && !detail.quality_report.checks && (
                <pre className="error-detail" style={{ maxHeight: 400 }}>
                  {JSON.stringify(detail.quality_report, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      )}

      <div style={{ marginTop: '2rem', textAlign: 'center', fontSize: '0.75rem', color: '#aaa' }}>
        Auto-refreshes every 10s
      </div>
    </div>
  );
}
