import { useState, useEffect } from 'react';
import { myJobs, type MyJobItem } from './api';

interface Props {
  lang: 'zh' | 'en';
}

export default function MyJobsPage({ lang }: Props) {
  const [jobs, setJobs] = useState<MyJobItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const t = (zh: string, en: string) => (lang === 'zh' ? zh : en);

  const fetchJobs = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await myJobs();
      setJobs(data.jobs);
    } catch (err: any) {
      setError(err.message || 'Failed to load jobs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchJobs(); }, []);

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

  return (
    <div className="my-page">
      <div className="studio-header">
        <h2>{t('我的任务', 'My Jobs')}</h2>
        <p className="studio-subtitle">
          {t('查看您的生成历史和下载链接。', 'View your generation history and download links.')}
        </p>
      </div>

      {loading && <p className="muted-text">{t('加载中...', 'Loading...')}</p>}
      {error && <div className="status error">{error}</div>}

      {!loading && jobs.length === 0 && (
        <div className="empty-state">
          <p>{t('暂无生成任务', 'No jobs yet')}</p>
          <span className="muted-text">
            {t('返回 Studio 创建您的第一个 HTML PPT。', 'Go back to Studio to create your first HTML PPT.')}
          </span>
        </div>
      )}

      {jobs.length > 0 && (
        <div className="jobs-table-wrap">
          <table className="jobs-table">
            <thead>
              <tr>
                <th>{t('主题', 'Topic')}</th>
                <th>{t('状态', 'Status')}</th>
                <th>{t('质量', 'Quality')}</th>
                <th>{t('时间', 'Time')}</th>
                <th>{t('下载', 'Download')}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(j => (
                <tr key={j.job_id}>
                  <td className="ellipsis" title={j.topic}>{j.topic?.slice(0, 50) || '-'}</td>
                  <td>{statusBadge(j.status)}</td>
                  <td>
                    {j.quality_score != null ? (
                      <span style={{
                        fontWeight: 600,
                        color: j.quality_status === 'pass' ? '#22c55e' : j.quality_status === 'fail' ? '#ef4444' : '#f59e0b',
                      }}>
                        {j.quality_score}/100
                      </span>
                    ) : '-'}
                  </td>
                  <td className="time-cell">
                    {j.created_at ? new Date(j.created_at).toLocaleString() : '-'}
                  </td>
                  <td>
                    <div className="job-links">
                      {j.download_standalone_url && (
                        <a href={j.download_standalone_url} className="mini-link accent">
                          {t('下载 Standalone', 'Download Standalone')}
                        </a>
                      )}
                      {j.status === 'success' && !j.download_standalone_url && (
                        <span className="muted-text">{t('无文件', 'N/A')}</span>
                      )}
                      {j.status !== 'success' && <span className="muted-text">-</span>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
