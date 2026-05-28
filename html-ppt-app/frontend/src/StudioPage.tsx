import { useState, useRef, useCallback, useEffect } from 'react';
import { createJob, getJob, authDownloadUrl, submitFeedback, getFeedback, type GenerateRequest, type JobResponse, type FeedbackResponse } from './api';
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
  const [feedback, setFeedback] = useState<FeedbackResponse | null>(null);
  const [feedbackForm, setFeedbackForm] = useState({
    rating: 5, content_accuracy: 4, visual_quality: 4, usefulness: 4,
    would_use_again: true, most_needed_feature: '', comment: '',
  });
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [feedbackError, setFeedbackError] = useState('');
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
            // Load existing feedback
            try {
              const fb = await getFeedback(j.job_id);
              setFeedback(fb);
              setFeedbackSubmitted(true);
            } catch {
              setFeedback(null);
              setFeedbackSubmitted(false);
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
              const fb = await getFeedback(savedJobId);
              setFeedback(fb);
              setFeedbackSubmitted(true);
            } catch {
              setFeedback(null);
              setFeedbackSubmitted(false);
            }
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
    setFeedback(null);
    setFeedbackSubmitted(false);
    setFeedbackError('');
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
              {/* Report (standalone) — primary */}
              <div className="link-group">
                <h4>{t('报告', 'Report')}</h4>
                <p className="link-desc">{t('可复制到任意电脑离线打开', 'Copy to any computer, works offline')}</p>
                <div className="link-row">
                  {job.preview_standalone_url && (
                    <a href={authDownloadUrl(job.preview_standalone_url)} target="_blank" rel="noopener noreferrer" className="result-link accent">
                      {t('预览', 'Preview')}
                    </a>
                  )}
                  {job.download_standalone_url && (
                    <a href={authDownloadUrl(job.download_standalone_url)} className="result-link accent">
                      {t('下载 HTML PPT', 'Download HTML PPT')}
                    </a>
                  )}
                </div>
              </div>
            </div>

            {/* Feedback Card (Phase 5E) */}
            <div className="feedback-card">
              <h4>{t('反馈', 'Feedback')}</h4>
              <p className="feedback-desc">
                {t('帮助我们改进生成质量（可选）', 'Help us improve generation quality (optional)')}
              </p>

              {feedbackSubmitted ? (
                <div className="feedback-done">
                  <span style={{ color: '#22c55e', fontSize: '1.2rem' }}>✓</span>{' '}
                  {t('感谢您的反馈！', 'Thank you for your feedback!')}
                  {feedback && (
                    <button className="link-btn" style={{ marginLeft: '0.75rem', fontSize: '0.8rem' }}
                      onClick={() => { setFeedbackSubmitted(false); setFeedback(feedback); }}>
                      {t('修改', 'Edit')}
                    </button>
                  )}
                </div>
              ) : (
                <div className="feedback-form">
                  <div className="feedback-row">
                    <label>{t('1. 内容是否准确？', '1. Content accuracy?')}</label>
                    <div className="star-row">
                      {[1,2,3,4,5].map(n => (
                        <button key={n} type="button"
                          className={`star-btn ${n <= feedbackForm.content_accuracy ? 'active' : ''}`}
                          onClick={() => setFeedbackForm({...feedbackForm, content_accuracy: n})}
                        >{n <= feedbackForm.content_accuracy ? '★' : '☆'}</button>
                      ))}
                    </div>
                  </div>
                  <div className="feedback-row">
                    <label>{t('2. 页面是否专业？', '2. Visual quality?')}</label>
                    <div className="star-row">
                      {[1,2,3,4,5].map(n => (
                        <button key={n} type="button"
                          className={`star-btn ${n <= feedbackForm.visual_quality ? 'active' : ''}`}
                          onClick={() => setFeedbackForm({...feedbackForm, visual_quality: n})}
                        >{n <= feedbackForm.visual_quality ? '★' : '☆'}</button>
                      ))}
                    </div>
                  </div>
                  <div className="feedback-row">
                    <label>{t('3. 是否比你自己整理快？', '3. Faster than doing it yourself?')}</label>
                    <div className="star-row">
                      {[1,2,3,4,5].map(n => (
                        <button key={n} type="button"
                          className={`star-btn ${n <= feedbackForm.usefulness ? 'active' : ''}`}
                          onClick={() => setFeedbackForm({...feedbackForm, usefulness: n})}
                        >{n <= feedbackForm.usefulness ? '★' : '☆'}</button>
                      ))}
                    </div>
                  </div>
                  <div className="feedback-row">
                    <label>{t('4. 是否愿意继续使用？', '4. Would you use it again?')}</label>
                    <div className="bool-row">
                      <button
                        type="button"
                        className={`bool-btn ${feedbackForm.would_use_again ? 'active yes' : ''}`}
                        onClick={() => setFeedbackForm({...feedbackForm, would_use_again: true})}
                      >{t('愿意', 'Yes')}</button>
                      <button
                        type="button"
                        className={`bool-btn ${!feedbackForm.would_use_again ? 'active no' : ''}`}
                        onClick={() => setFeedbackForm({...feedbackForm, would_use_again: false})}
                      >{t('不愿意', 'No')}</button>
                    </div>
                  </div>
                  <div className="feedback-row">
                    <label>{t('5. 最想要哪个功能？', '5. Most needed feature?')}</label>
                    <select
                      value={feedbackForm.most_needed_feature}
                      onChange={e => setFeedbackForm({...feedbackForm, most_needed_feature: e.target.value})}
                      className="feedback-select"
                    >
                      <option value="">{t('— 选择 —', '— Select —')}</option>
                      <option value="images">{t('图片/图表', 'Images / Charts')}</option>
                      <option value="charts">{t('数据图表', 'Data Charts')}</option>
                      <option value="editing">{t('在线编辑', 'Online Editing')}</option>
                      <option value="pptx">{t('PPTX 导出', 'PPTX Export')}</option>
                      <option value="deep_research">{t('深度研究', 'Deep Research')}</option>
                    </select>
                  </div>
                  <div className="feedback-row">
                    <label>{t('6. 其他意见', '6. Other comments')}</label>
                    <textarea
                      rows={2}
                      value={feedbackForm.comment}
                      onChange={e => setFeedbackForm({...feedbackForm, comment: e.target.value})}
                      placeholder={t('任何建议或发现的问题...', 'Any suggestions or issues...')}
                      className="feedback-textarea"
                    />
                  </div>
                  <div className="feedback-row">
                    <label>{t('综合评分', 'Overall rating')}</label>
                    <div className="star-row">
                      {[1,2,3,4,5].map(n => (
                        <button key={n} type="button"
                          className={`star-btn big ${n <= feedbackForm.rating ? 'active' : ''}`}
                          onClick={() => setFeedbackForm({...feedbackForm, rating: n})}
                        >{n <= feedbackForm.rating ? '★' : '☆'}</button>
                      ))}
                    </div>
                  </div>
                  {feedbackError && <p style={{ color: '#ef4444', fontSize: '0.85rem' }}>{feedbackError}</p>}
                  <button
                    className="btn-primary"
                    style={{ marginTop: '0.5rem', padding: '0.5rem 1.5rem', fontSize: '0.9rem' }}
                    disabled={feedbackSubmitting}
                    onClick={async () => {
                      setFeedbackSubmitting(true);
                      setFeedbackError('');
                      try {
                        const fb = await submitFeedback(job.job_id, {
                          rating: feedbackForm.rating,
                          content_accuracy: feedbackForm.content_accuracy,
                          visual_quality: feedbackForm.visual_quality,
                          usefulness: feedbackForm.usefulness,
                          would_use_again: feedbackForm.would_use_again,
                          most_needed_feature: feedbackForm.most_needed_feature || undefined,
                          comment: feedbackForm.comment || undefined,
                        });
                        setFeedback(fb);
                        setFeedbackSubmitted(true);
                      } catch (err: any) {
                        setFeedbackError(err.message || 'Failed to submit feedback');
                      } finally {
                        setFeedbackSubmitting(false);
                      }
                    }}
                  >
                    {t('提交反馈', 'Submit Feedback')}
                  </button>
                </div>
              )}
            </div>
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
