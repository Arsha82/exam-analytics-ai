import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { v2, type CourseSummary, type SystemStatus } from '../../api/v2';
import { COURSE_TABS } from '../../pages/v2/courseTabs';
import styles from './AppShell.module.css';

const CLASSIC = [
  { to: '/classic', label: 'Dashboard' },
  { to: '/papers', label: 'Papers' },
  { to: '/questions', label: 'Questions' },
  { to: '/syllabus', label: 'Syllabus' },
  { to: '/analysis', label: 'Analysis' },
  { to: '/predictions', label: 'Predict' },
  { to: '/attempts', label: 'Attempts' },
  { to: '/mastery', label: 'Mastery' },
  { to: '/review', label: 'Review queue' },
];

function crumbs(pathname: string): string[] {
  if (pathname === '/') return ['Home'];
  const parts = pathname.split('/').filter(Boolean);
  if (parts[0] === 'courses') return ['Subjects', ...(parts[1] ? [parts[1]] : []), ...(parts[2] ? [parts[2]] : [])];
  if (parts[0] === 'jobs') return ['Jobs'];
  if (parts[0] === 'academics') return ['Academics'];
  if (parts[0] === 'settings') return ['Settings'];
  return ['Classic', parts[0]];
}

const linkClass = ({ isActive }: { isActive: boolean }) => `${styles.link} ${isActive ? styles.linkActive : ''}`;

export default function AppShell() {
  const location = useLocation();
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem('pyq-theme') ?? 'light';
    } catch {
      return 'light';
    }
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem('pyq-theme', theme);
    } catch {
      /* private mode */
    }
  }, [theme]);

  useEffect(() => {
    v2.courses().then(setCourses).catch(() => setCourses([]));
    v2.system().then(setStatus).catch(() => setStatus(null));
  }, [location.pathname]);

  const isClassic = CLASSIC.some((c) => location.pathname.startsWith(c.to));
  const [, first, courseFromPath, tabPart] = location.pathname.split('/');
  const activeCourse = first === 'courses' ? courseFromPath : undefined;
  const activeTab = activeCourse ? tabPart || 'overview' : undefined;

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <NavLink to="/" className={styles.brand}>
          <span className={styles.brandMark}>PYQ</span>
          <span className={styles.brandSub}>analyzer</span>
        </NavLink>

        <nav className={styles.nav} aria-label="Main">
          <div className={styles.group}>
            <NavLink to="/" end className={linkClass}>Home</NavLink>
            <NavLink to="/academics" className={linkClass}>Academics</NavLink>
            <NavLink to="/courses" end className={linkClass}>Subjects</NavLink>
            {courses.map((c) => {
              const open = activeCourse === c.code;
              return (
                <div key={c.code}>
                  <NavLink to={`/courses/${c.code}`} className={({ isActive }) => `${styles.sublink} ${isActive ? styles.sublinkActive : ''}`}>
                    <span className={styles.code}>{c.code}</span>
                    <span className={styles.subTitle}>{c.title}</span>
                  </NavLink>
                  {open && (
                    <div className={styles.sections}>
                      {COURSE_TABS.map((t) => (
                        <NavLink key={t.key} to={`/courses/${c.code}/${t.key}`}
                          className={() => `${styles.section} ${activeCourse === c.code && activeTab === t.key ? styles.sectionActive : ''}`}>
                          {t.label}
                        </NavLink>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div className={styles.group}>
            <div className={styles.groupLabel}>System</div>
            <NavLink to="/jobs" className={linkClass}>Jobs</NavLink>
            <NavLink to="/settings" className={linkClass}>Settings</NavLink>
          </div>
          <details className={styles.group} open={isClassic}>
            <summary className={styles.groupLabel}>Old pages (v1)</summary>
            {CLASSIC.map((c) => (
              <NavLink key={c.to} to={c.to} className={linkClass}>{c.label}</NavLink>
            ))}
          </details>
        </nav>

        <div className={styles.sidebarFoot}>
          <SystemDot label="agy" ok={status?.agy.available} title={status?.agy.reason ?? 'agy CLI ready'} />
          <SystemDot label="OCR" ok={status?.local_ocr.available} title={status?.local_ocr.reason ?? status?.local_ocr.model ?? ''} />
          <SystemDot label="podman" ok={status?.podman.available} title={status?.podman.binary ?? 'not found'} />
        </div>
      </aside>

      <div className={styles.main}>
        <header className={styles.topbar}>
          <ol className={styles.crumbs}>
            {crumbs(location.pathname).map((c, i, all) => (
              <li key={i} className={i === all.length - 1 ? styles.crumbCurrent : undefined}>{c}</li>
            ))}
          </ol>
          <button
            className={styles.themeBtn}
            onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          >
            {theme === 'dark' ? 'Paper' : 'Night'}
          </button>
        </header>
        <main className={styles.content}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function SystemDot({ label, ok, title }: { label: string; ok?: boolean; title?: string }) {
  return (
    <span className={styles.sys} title={title}>
      <span className={ok === undefined ? styles.dotUnknown : ok ? styles.dotOk : styles.dotBad} />
      {label}
    </span>
  );
}
