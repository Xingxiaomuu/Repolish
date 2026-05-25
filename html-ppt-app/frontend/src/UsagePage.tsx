import { useState, useEffect } from 'react';
import { myUsage, type MyUsageResponse } from './api';

interface Props {
  lang: 'zh' | 'en';
}

export default function UsagePage({ lang }: Props) {
  const [usage, setUsage] = useState<MyUsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const t = (zh: string, en: string) => (lang === 'zh' ? zh : en);

  useEffect(() => {
    setLoading(true);
    setError('');
    myUsage()
      .then(setUsage)
      .catch(err => setError(err.message || 'Failed to load usage'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="my-page">
      <div className="studio-header">
        <h2>{t('用量统计', 'Usage')}</h2>
        <p className="studio-subtitle">
          {t('查看您本月的免费生成使用情况。', 'View your free generation usage for this month.')}
        </p>
      </div>

      {loading && <p className="muted-text">{t('加载中...', 'Loading...')}</p>}
      {error && <div className="status error">{error}</div>}

      {usage && (
        <div className="usage-cards">
          <div className="usage-card">
            <strong>{usage.month}</strong>
            <span>{t('当月', 'Current Month')}</span>
          </div>
          <div className="usage-card accent">
            <strong>{usage.used} / {usage.limit}</strong>
            <span>{t('已用次数', 'Used')}</span>
          </div>
          <div className="usage-card green">
            <strong>{usage.remaining}</strong>
            <span>{t('剩余次数', 'Remaining')}</span>
          </div>
          <div className="usage-card">
            <strong>{usage.success_jobs}</strong>
            <span>{t('成功任务', 'Success')}</span>
          </div>
          <div className="usage-card red">
            <strong>{usage.failed_jobs}</strong>
            <span>{t('失败任务', 'Failed')}</span>
          </div>
        </div>
      )}

      {usage && usage.remaining === 0 && (
        <div className="quality-hint warning" style={{ marginTop: '1rem' }}>
          {t(
            '您本月的免费生成次数已用完。下月自动重置。如需更多次数，请联系管理员。',
            'You have used all your free generations this month. The limit resets next month. Contact the admin if you need more.'
          )}
        </div>
      )}
    </div>
  );
}
