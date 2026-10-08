import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import styles from './Dashboard.module.css';
import { apiClient, type Paper, type MasteryResponse } from '../api/client';

export default function Dashboard() {
  const [stats, setStats] = useState({
    papers: 0,
    questions: 0,
    topicsMapped: 0,
    masteryAvg: 0,
  });
  const [recentPapers, setRecentPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    try {
      setLoading(true);
      const [papersData, questionsData, masteryData] = await Promise.allSettled([
        apiClient.getPapers(),
        apiClient.getQuestions({ limit: 100 }),
        apiClient.getMastery(),
      ]);

      const papers = papersData.status === 'fulfilled' ? papersData.value.papers : [];
      const questions = questionsData.status === 'fulfilled' ? questionsData.value.questions : [];
      const mastery: MasteryResponse | null = masteryData.status === 'fulfilled' ? masteryData.value : null;

      const mappedQuestions = questions.filter((q) => q.unit_guess && q.unit_guess !== 'General' && !q.needs_review);
      const topicsMappedPct = questions.length > 0 ? Math.round((mappedQuestions.length / questions.length) * 100) : 0;

      setStats({
        papers: papers.length,
        questions: questionsData.status === 'fulfilled' ? questionsData.value.total : 0,
        topicsMapped: topicsMappedPct,
        masteryAvg: mastery?.overall_readiness_pct || 0,
      });

      setRecentPapers(papers.slice(0, 5));
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();

    // Listen to WebSocket for live pipeline events to refresh dashboard
    const ws = apiClient.createPipelineWebSocket((event) => {
      if (event.stage === 'complete' || event.progress === 100) {
        loadData();
      }
    });

    return () => {
      ws.close();
    };
  }, []);

  const hasData = stats.papers > 0;

  return (
    <div className={styles.dashboard}>
      {/* ── Header ── */}
      <div className={styles.dashboard__header}>
        <div>
          <h1>Dashboard</h1>
          <p>Closed-loop question paper intelligence & adaptive practice engine.</p>
        </div>
      </div>

      {/* ── Stat cards ── */}
      <div className={`${styles['stats-grid']} stagger-enter`}>
        <StatCard
          label="Papers Ingested"
          value={loading ? '...' : stats.papers}
          icon={<FileSmallIcon />}
        />
        <StatCard
          label="Questions Extracted"
          value={loading ? '...' : stats.questions}
          icon={<HashIcon />}
        />
        <StatCard
          label="Topics Mapped"
          value={loading ? '...' : (stats.topicsMapped > 0 ? `${stats.topicsMapped}%` : '—')}
          icon={<MapIcon />}
        />
        <StatCard
          label="Avg. Readiness"
          value={loading ? '...' : (stats.masteryAvg > 0 ? `${stats.masteryAvg}%` : '—')}
          icon={<TrendUpIcon />}
        />
      </div>

      {/* ── Quick actions ── */}
      <div className={styles.section}>
        <div className={styles.section__header}>
          <h2>Quick Actions</h2>
        </div>
        <div className={styles['quick-actions']}>
          <Link to="/papers" className={`card pressable ${styles['quick-action']}`}>
            <div className={`${styles['quick-action__icon']} ${styles['quick-action__icon--purple']}`}>
              <UploadIcon />
            </div>
            <div className={styles['quick-action__text']}>
              <h3>Upload Exam Papers</h3>
              <p>Scan PDFs or images with Unlimited-OCR and gemma4:12b.</p>
            </div>
          </Link>

          <Link to="/analysis" className={`card pressable ${styles['quick-action']}`}>
            <div className={`${styles['quick-action__icon']} ${styles['quick-action__icon--green']}`}>
              <BarChartIcon />
            </div>
            <div className={styles['quick-action__text']}>
              <h3>Pattern Intelligence</h3>
              <p>Topic frequencies, yearly trend slopes, and twisted question detection.</p>
            </div>
          </Link>

          <Link to="/predictions" className={`card pressable ${styles['quick-action']}`}>
            <div className={`${styles['quick-action__icon']} ${styles['quick-action__icon--amber']}`}>
              <SparkleIcon />
            </div>
            <div className={styles['quick-action__text']}>
              <h3>Generate Prediction</h3>
              <p>Synthesize weighted exam papers with detailed checklist rubrics.</p>
            </div>
          </Link>
        </div>
      </div>

      {/* ── Recent Activity ── */}
      <div className={styles.section}>
        <div className={styles.section__header}>
          <h2>Recent Papers & Pipeline Activity</h2>
        </div>
        <div className="card">
          {hasData ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '8px 0' }}>
              {recentPapers.map((paper) => (
                <div
                  key={paper.paper_id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 16px',
                    borderRadius: '8px',
                    backgroundColor: '#f8fafc',
                    border: '1px solid #e2e8f0',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div
                      style={{
                        width: '36px',
                        height: '36px',
                        borderRadius: '8px',
                        backgroundColor: '#e0e7ff',
                        color: '#4f46e5',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontWeight: 600,
                      }}
                    >
                      {paper.year}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, color: '#0f172a' }}>{paper.subject}</div>
                      <div style={{ fontSize: '13px', color: '#64748b' }}>
                        {paper.question_count} questions • {paper.total_marks} Marks • Status: {paper.ocr_status}
                      </div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {paper.needs_review && (
                      <span
                        style={{
                          backgroundColor: '#fef3c7',
                          color: '#b45309',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          fontSize: '12px',
                          fontWeight: 500,
                        }}
                      >
                        Needs Review
                      </span>
                    )}
                    <Link
                      to="/questions"
                      style={{
                        fontSize: '13px',
                        color: '#2563eb',
                        textDecoration: 'none',
                        fontWeight: 500,
                      }}
                    >
                      View Questions →
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles['empty-state']}>
              <div className={styles['empty-state__icon']}>
                <InboxIcon />
              </div>
              <h3>No papers uploaded yet</h3>
              <p>Upload your first question paper to get started with analysis and predictions.</p>
              <div style={{ marginTop: '16px' }}>
                <Link
                  to="/papers"
                  className="btn btn--primary"
                  style={{ textDecoration: 'none' }}
                >
                  Upload Your First Paper
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  icon,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
}) {
  return (
    <div className={`card ${styles['stat-card']}`}>
      <div className={styles['stat-card__label']}>
        {icon}
        {label}
      </div>
      <div className={styles['stat-card__value']}>{value}</div>
    </div>
  );
}

function FileSmallIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z"/><polyline points="14,2 14,8 20,8"/></svg>;
}

function HashIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>;
}

function MapIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polygon points="1,6 1,22 8,18 16,22 23,18 23,2 16,6 8,2"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>;
}

function TrendUpIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="23,6 13.5,15.5 8.5,10.5 1,18"/><polyline points="17,6 23,6 23,12"/></svg>;
}

function UploadIcon() {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17,8 12,3 7,8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>;
}

function BarChartIcon() {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>;
}

function SparkleIcon() {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"><path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z"/></svg>;
}

function InboxIcon() {
  return <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round"><polyline points="22,12 16,12 14,15 10,15 8,12 2,12"/><path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z"/></svg>;
}
