import { useState } from 'react';
import { getSavedUser, clearToken } from './api';
import StudioPage from './StudioPage';
import MyJobsPage from './MyJobsPage';
import UsagePage from './UsagePage';

type Page = 'studio' | 'jobs' | 'usage';

interface Props {
  onLogout: () => void;
}

export default function MainLayout({ onLogout }: Props) {
  const [page, setPage] = useState<Page>('studio');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [lang, setLang] = useState<'zh' | 'en'>('zh');
  const user = getSavedUser();

  const handleLogout = () => {
    clearToken();
    onLogout();
  };

  const closeSidebar = () => setSidebarOpen(false);

  const t = (zh: string, en: string) => (lang === 'zh' ? zh : en);

  const navItems: { key: Page; labelZh: string; labelEn: string; icon: string }[] = [
    { key: 'studio', labelZh: '新建生成', labelEn: 'New Generation', icon: '+' },
    { key: 'jobs', labelZh: '我的任务', labelEn: 'My Jobs', icon: '&#9776;' },
    { key: 'usage', labelZh: '用量统计', labelEn: 'Usage', icon: '&#9733;' },
  ];

  return (
    <div className="app-shell">
      {/* Mobile overlay */}
      {sidebarOpen && <div className="sidebar-overlay" onClick={closeSidebar} />}

      {/* Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <span className="logo-icon">&#9650;</span>
            <span className="logo-text">HTML PPT Studio</span>
          </div>
        </div>

        {user && (
          <div className="sidebar-user">
            <div className="user-avatar">{user.name.charAt(0).toUpperCase()}</div>
            <div className="user-info">
              <div className="user-name">{user.name}</div>
              <div className="user-email">{user.email}</div>
            </div>
          </div>
        )}

        <nav className="sidebar-nav">
          {navItems.map(item => (
            <button
              key={item.key}
              className={`nav-item ${page === item.key ? 'active' : ''}`}
              onClick={() => { setPage(item.key); closeSidebar(); }}
            >
              <span className="nav-icon" dangerouslySetInnerHTML={{ __html: item.icon }} />
              <span>{t(item.labelZh, item.labelEn)}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-lang">
            <button className={`lang-btn ${lang === 'zh' ? 'active' : ''}`} onClick={() => setLang('zh')}>中</button>
            <button className={`lang-btn ${lang === 'en' ? 'active' : ''}`} onClick={() => setLang('en')}>EN</button>
          </div>
          <button className="nav-item logout-btn" onClick={handleLogout}>
            <span className="nav-icon">&#8592;</span>
            <span>{t('退出登录', 'Logout')}</span>
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="main-area">
        {/* Mobile header */}
        <header className="mobile-header">
          <button className="hamburger" onClick={() => setSidebarOpen(true)}>
            &#9776;
          </button>
          <span className="mobile-title">HTML PPT Studio</span>
          <button className="lang-btn mobile-lang" onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}>
            {lang === 'zh' ? 'EN' : '中'}
          </button>
        </header>

        <div className="page-content">
          {page === 'studio' && <StudioPage lang={lang} />}
          {page === 'jobs' && <MyJobsPage lang={lang} />}
          {page === 'usage' && <UsagePage lang={lang} />}
        </div>
      </main>
    </div>
  );
}
