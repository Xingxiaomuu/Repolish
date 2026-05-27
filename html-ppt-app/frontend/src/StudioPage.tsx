import { useState, useRef, useCallback, useEffect } from 'react';
import { createJob, getJob, getArtifacts, authDownloadUrl, type GenerateRequest, type JobResponse, type ArtifactInfo } from './api';
import { EXAMPLE_CARDS, type ExampleCard } from './examples';

interface Props {
  lang: 'zh' | 'en';
}

const STYLE_PRESETS = ['清淡', '暗色', '明亮', '职业', '科技', '极简', '市场研究'];
const DEFAULT_STYLE = 'Professional, bright, clean, research-oriented';
const ACTIVE_JOB_KEY = 'slidehttp_active_job';

export default function StudioPage({ lang }: Props) {
  const [topic, setTopic] = useState('');
  const [content, setContent] = useState('');
  const [language, setLanguage] = useState('English');
  const [style, setStyle] = useState(DEFAULT_STYLE);
  const [customStyle, setCustomStyle] = useState('');
  const [selectedStylePreset, setSelectedStylePreset] = useState<string | null>(null);
  const [slideCount, setSlideCount] = useState(12);
  const [audience, setAudience] = useState('');
  const [extraRequirements, setExtraRequirements] = useState('');
  const [searchLevel, setSearchLevel] = useState<'none' | 'light' | 'deep'>('none');

  // Example modal
  const [exampleModal, setExampleModal] = useState<ExampleCard | null>(null);
  const [exampleContentExpanded, setExampleContentExpanded] = useState(false);

  const [loading, setLoading] = useState(false);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const t = (zh: string, en: string) => (lang === 'zh' ? zh : en);

  const clearPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const clearActiveJob = useCallback(() => {
    localStorage.removeItem(ACTIVE_JOB_KEY);
  }, []);

  const startPolling = useCallback((jobId: string) => {
    clearPolling();
    localStorage.setItem(ACTIVE_JOB_KEY, jobId);
    pollingRef.current = setInterval(async () => {
      try {
        const j = await getJob(jobId);
        setJob(j);
        if (j.status === 'success' || j.status === 'failed') {
          clearPolling();
          clearActiveJob();
          setLoading(false);
          if (j.status === 'success') {
            try {
              const a = await getArtifacts(j.job_id);
              setArtifacts(a.artifacts);
            } catch {
              setArtifacts([]);
            }
          }
        }
      } catch (err: any) {
        setError(err.message || 'Failed to poll job status');
        clearPolling();
        clearActiveJob();
        setLoading(false);
      }
    }, 2000);
  }, [clearPolling, clearActiveJob]);

  // Restore active job on mount (survives page switches)
  useEffect(() => {
    const savedJobId = localStorage.getItem(ACTIVE_JOB_KEY);
    if (!savedJobId) return;

    const restore = async () => {
      try {
        const j = await getJob(savedJobId);
        if (j.status === 'queued' || j.status === 'running') {
          setJob(j);
          setLoading(true);
          startPolling(savedJobId);
        } else {
          // Job already finished — show results, clear saved key
          setJob(j);
          clearActiveJob();
          if (j.status === 'success') {
            try {
              const a = await getArtifacts(j.job_id);
              setArtifacts(a.artifacts);
            } catch { /* ignore */ }
          }
        }
      } catch {
        // Job not found or error — clean up
        clearActiveJob();
      }
    };
    restore();

    return () => clearPolling();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    setJob(null);
    setArtifacts([]);
    setRemaining(null);

    const req: GenerateRequest = {
      topic,
      content,
      language: language || 'English',
      style: effectiveStyle,
      slide_count: effectiveSlideCount,
      audience,
      extra_requirements: extraRequirements,
      search_level: searchLevel,
    };

    try {
      const res = await createJob(req);
      setJob({ job_id: res.job_id, status: res.status });
      setRemaining(res.remaining_generations);
      startPolling(res.job_id);
    } catch (err: any) {
      setError(err.message || 'Failed to create job');
      setLoading(false);
    }
  };

  const effectiveStyle = customStyle.trim() || style || DEFAULT_STYLE;
  const effectiveSlideCount = slideCount || 12;

  const statusLabel = (j: JobResponse) => {
    switch (j.status) {
      case 'queued': {
        const pos = j.queue_position;
        return pos
          ? t(`排队中 — 位置 #${pos}`, `Queued — position #${pos}`)
          : t('排队中 — 等待 worker...', 'Queued — waiting for worker...');
      }
      case 'running': {
        const wn = j.worker_name;
        return wn
          ? t(`生成中... (${wn})`, `Generating... (${wn})`)
          : t('生成中...', 'Generating...');
      }
      case 'success': return t('生成成功！', 'Success!');
      case 'failed': return t('生成失败', 'Failed');
      default: return j.status;
    }
  };

  const isTerminal = job?.status === 'success' || job?.status === 'failed';

  return (
    <div className="studio-page">
      {/* Header */}
      <div className="studio-header">
        <h2>{t('长报告转 HTML PPT', 'Long Report to HTML PPT')}</h2>
        <p className="studio-subtitle">
          {t('将冗长报告、文字材料转化成可汇报PPT', 'Turn lengthy reports and text materials into presentable PPTs')}
        </p>
      </div>

      {/* Example Showcase Cards */}
      <div className="example-section">
        <h3 className="example-section-title">
          {t('示例展示', 'Example Showcase')}
          <span className="example-section-hint">
            {t(' — 点击卡片查看提示词和渲染效果', ' — click to see prompts & rendered output')}
          </span>
        </h3>
        <div className="preset-cards example-cards">
          {EXAMPLE_CARDS.map(card => (
            <button
              key={card.id}
              className="preset-card example-card"
              onClick={() => { setExampleModal(card); setExampleContentExpanded(false); }}
            >
              <div className="preset-card-title">{card.title}</div>
              <div className="preset-card-desc">{card.description}</div>
              <div className="preset-card-badge">{card.badge}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Form */}
      <div className="studio-form">
        {/* Row 1: Topic + Language */}
        <div className="form-row">
          <div className="field flex-2">
            <label htmlFor="topic">{t('报告主题', 'Report Topic')}</label>
            <input
              id="topic"
              type="text"
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder={t('例如：亚太音频市场调研报告', 'e.g. Asia-Pacific Audio Market Research Report')}
            />
          </div>
          <div className="field flex-1">
            <label htmlFor="lang">{t('语言', 'Language')}</label>
            <input
              id="lang"
              type="text"
              value={language}
              onChange={e => setLanguage(e.target.value)}
              placeholder="English, 中文, 日本語..."
            />
          </div>
        </div>

        {/* Row 2: Content */}
        <div className="field full-width">
          <label htmlFor="content">{t('报告内容', 'Report Content')}</label>
          <textarea
            id="content"
            rows={10}
            value={content}
            onChange={e => setContent(e.target.value)}
            placeholder={t(
              '在此粘贴您的长报告、研究备忘录、会议纪要或市场分析...',
              'Paste your long report, research memo, meeting notes, or market analysis here.'
            )}
          />
        </div>

        {/* Row 3: Style + Slide Count */}
        <div className="form-row">
          <div className="field flex-2">
            <label>{t('风格', 'Style')}</label>
            <div className="preset-row">
              {STYLE_PRESETS.map(s => (
                <button
                  key={s}
                  type="button"
                  className={`preset-btn ${selectedStylePreset === s && !customStyle ? 'active' : ''}`}
                  onClick={() => { setStyle(s); setSelectedStylePreset(s); setCustomStyle(''); }}
                >
                  {s}
                </button>
              ))}
            </div>
            <input
              type="text"
              value={customStyle}
              onChange={e => { setCustomStyle(e.target.value); setSelectedStylePreset(null); }}
              placeholder={t('或自定义描述，例如：专业、科技、清爽，偏市场洞察报告', 'Or custom: e.g. Professional, tech-focused, clean, market insight style')}
              className="custom-input"
              style={{ marginTop: '0.4rem' }}
            />
          </div>
          <div className="field flex-1">
            <label htmlFor="slides">{t('页数', 'Slide Count')}</label>
            <input
              id="slides"
              type="number"
              min={1}
              max={80}
              value={slideCount}
              onChange={e => setSlideCount(parseInt(e.target.value, 10) || 12)}
            />
          </div>
        </div>

        {/* Row 4: Audience + Search Level */}
        <div className="form-row">
          <div className="field flex-2">
            <label htmlFor="audience">{t('目标受众', 'Audience')}</label>
            <input
              id="audience"
              type="text"
              value={audience}
              onChange={e => setAudience(e.target.value)}
              placeholder={t('例如：战略投资部', 'e.g. Strategic Investment Department')}
            />
          </div>
          <div className="field flex-1">
            <label>{t('研究深度', 'Research Depth')}</label>
            <div className="search-level-row">
              {([
                ['none', t('不搜索', 'No Search'), t('仅用报告内容', 'Use only my content')],
                ['light', t('轻量搜索', 'Light Search'), t('5-6次搜索补充关键数据', '5-6 searches for key data')],
                ['deep', t('深度研究', 'Deep Research'), t('全面搜索 + 引用页 [1][2]', 'Full research + citation page [1][2]')],
              ] as const).map(([val, label, desc]) => (
                <button
                  key={val}
                  type="button"
                  className={`search-level-btn ${searchLevel === val ? 'active' : ''}`}
                  onClick={() => setSearchLevel(val)}
                >
                  <span className="sl-label">{label}</span>
                  <span className="sl-desc">{desc}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Row 5: Extra Requirements */}
        <div className="field full-width">
          <label htmlFor="extra">{t('额外要求', 'Extra Requirements')}</label>
          <textarea
            id="extra"
            rows={2}
            value={extraRequirements}
            onChange={e => setExtraRequirements(e.target.value)}
            placeholder={t(
              '例如：支持键盘导航、主题切换、演讲者备注、图表、表格...',
              'e.g. Support keyboard navigation, theme switching, speaker notes, charts, tables...'
            )}
          />
        </div>

        {/* Generate Button */}
        <div className="field full-width">
          <button
            className="btn-primary btn-generate"
            onClick={handleSubmit}
            disabled={loading && !isTerminal}
          >
            {loading && !isTerminal
              ? t('生成中...', 'Generating...')
              : t('生成 PPT', 'Generate PPT')}
          </button>
        </div>

        {/* Remaining */}
        {remaining != null && (
          <div className="usage-info">
            {remaining > 0
              ? t(`本月剩余免费次数：${remaining}`, `Remaining free generations this month: ${remaining}`)
              : t('这是您本月最后一次免费生成。', 'This was your last free generation this month.')}
          </div>
        )}

        {/* Job status — queued / running */}
        {job && !isTerminal && (
          <div className="status loading full-width">
            <div className="spinner" />
            <div>
              <strong>{statusLabel(job)}</strong>
              <p className="job-id-label">Job: {job.job_id}</p>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="status error full-width">
            <strong>{t('错误：', 'Error: ')}</strong> {error}
          </div>
        )}

        {/* Success */}
        {job && job.status === 'success' && (
          <div className="status success full-width">
            <h3>{t('PPT 生成成功！', 'PPT Generated Successfully!')}</h3>
            <p className="job-id-label">Job: {job.job_id}</p>
            {job.quality_status === 'warning' && (
              <div className="quality-hint warning">
                {t('生成完成，但建议人工检查内容完整性。', 'Generation complete, but we recommend manually reviewing content completeness.')}
              </div>
            )}
            {job.quality_status === 'fail' && (
              <div className="quality-hint fail">
                {t('生成结果存在明显问题，请检查或重新生成。', 'The result has noticeable issues — please review or regenerate.')}
              </div>
            )}
            <div className="result-links">
              {/* Standard Version */}
              <div className="link-group">
                <h4>{t('标准版本', 'Standard Version')}</h4>
                <p className="link-desc">{t('需要服务器上的 html-ppt skill 资源', 'Requires the html-ppt skill assets on the server')}</p>
                <div className="link-row">
                  {job.preview_url && (
                    <a href={authDownloadUrl(job.preview_url)} target="_blank" rel="noopener noreferrer" className="result-link">
                      {t('预览', 'Preview')}
                    </a>
                  )}
                  {job.download_html_url && (
                    <a href={authDownloadUrl(job.download_html_url)} className="result-link">
                      {t('下载 HTML', 'Download HTML')}
                    </a>
                  )}
                </div>
              </div>
              {/* Standalone Version */}
              {job.preview_standalone_url && (
                <div className="link-group">
                  <h4>{t('独立版本', 'Standalone Version')}</h4>
                  <p className="link-desc">{t('完全自包含 — 可复制到任意电脑离线打开', 'Fully self-contained — copy to any computer, works offline')}</p>
                  <div className="link-row">
                    <a href={authDownloadUrl(job.preview_standalone_url)} target="_blank" rel="noopener noreferrer" className="result-link accent">
                      {t('预览独立版', 'Preview Standalone')}
                    </a>
                    {job.download_standalone_url && (
                      <a href={authDownloadUrl(job.download_standalone_url)} className="result-link accent">
                        {t('下载独立版', 'Download Standalone')}
                      </a>
                    )}
                  </div>
                </div>
              )}
              {/* ZIP */}
              {job.download_zip_url && (
                <div className="link-group">
                  <h4>{t('打包下载', 'Bundle')}</h4>
                  <p className="link-desc">{t('ZIP 包含两个版本 + 日志', 'ZIP with both versions + logs')}</p>
                  <a href={authDownloadUrl(job.download_zip_url)} className="result-link">
                    {t('下载 ZIP', 'Download ZIP')}
                  </a>
                </div>
              )}
            </div>

            {/* Pipeline Artifacts */}
            {artifacts.length > 0 && (
              <div className="link-group">
                <h4>{t('处理产物', 'Pipeline Artifacts')}</h4>
                <p className="link-desc">{t('中间文件 — deck plan、context、质量报告', 'Intermediate files — deck plan, context, quality report')}</p>
                <div className="link-row">
                  {artifacts.map(a => (
                    <a
                      key={a.filename}
                      href={authDownloadUrl(a.url)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="result-link"
                      style={{ fontSize: '0.78rem', padding: '0.3rem 0.7rem' }}
                    >
                      {a.filename} ({(a.size / 1024).toFixed(1)} KB)
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Failed */}
        {job && job.status === 'failed' && (
          <div className="status error full-width">
            <strong>{t('生成失败', 'Generation Failed')}</strong>
            <p className="job-id-label">Job: {job.job_id}</p>
            {job.error_message && (
              <pre className="error-detail">{job.error_message}</pre>
            )}
            {job.logs_url && (
              <a href={authDownloadUrl(job.logs_url)} target="_blank" rel="noopener noreferrer" className="result-link" style={{ marginTop: '0.5rem', display: 'inline-block' }}>
                {t('查看日志', 'View Logs')}
              </a>
            )}
          </div>
        )}
      </div>

      {/* Example Modal */}
      {exampleModal && (
        <div className="modal-overlay" onClick={() => setExampleModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{exampleModal.title}</h3>
              <span className="modal-badge">{exampleModal.badge}</span>
              <button className="modal-close" onClick={() => setExampleModal(null)}>&times;</button>
            </div>

            <div className="modal-body">
              <div className="modal-prompt-grid">
                <div className="modal-field">
                  <label>{t('主题', 'Topic')}</label>
                  <div className="modal-value">{exampleModal.prompt.topic}</div>
                </div>
                <div className="modal-field">
                  <label>{t('语言', 'Language')}</label>
                  <div className="modal-value">{exampleModal.prompt.language}</div>
                </div>
                <div className="modal-field">
                  <label>{t('风格', 'Style')}</label>
                  <div className="modal-value">{exampleModal.prompt.style}</div>
                </div>
                <div className="modal-field">
                  <label>{t('页数 / 受众', 'Pages / Audience')}</label>
                  <div className="modal-value">{exampleModal.prompt.slide_count} pages / {exampleModal.prompt.audience}</div>
                </div>
              </div>

              <div className="modal-field">
                <label>{t('报告内容', 'Report Content')}</label>
                <div className={`modal-content-preview ${exampleContentExpanded ? 'expanded' : ''}`}>
                  <pre>{exampleModal.prompt.content}</pre>
                </div>
                {exampleModal.prompt.content.length > 400 && (
                  <button
                    className="link-btn modal-expand-btn"
                    onClick={() => setExampleContentExpanded(!exampleContentExpanded)}
                  >
                    {exampleContentExpanded ? t('收起 ▲', 'Collapse ▲') : t('展开全文 ▼', 'Expand ▼')}
                  </button>
                )}
              </div>

              {exampleModal.prompt.extra_requirements && (
                <div className="modal-field">
                  <label>{t('额外要求', 'Extra Requirements')}</label>
                  <div className="modal-value">{exampleModal.prompt.extra_requirements}</div>
                </div>
              )}

              <div className="modal-actions">
                <a
                  href={exampleModal.standaloneUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn-primary"
                >
                  {t('预览 Standalone HTML', 'Preview Standalone HTML')}
                </a>
                <a
                  href={exampleModal.standaloneUrl}
                  download
                  className="btn-secondary"
                >
                  {t('下载 Standalone', 'Download Standalone')}
                </a>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
