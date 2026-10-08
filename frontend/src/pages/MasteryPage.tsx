import { useEffect, useState } from 'react';
import { RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid, Cell } from 'recharts';
import s from '../design/shared.module.css';
import { apiClient, type MasteryItem, type MasteryResponse } from '../api/client';

const BUCKET_COLORS: Record<string, string> = {
  clear: '#16a34a',
  partial: '#d97706',
  weak: '#dc2626',
};

const BUCKET_LABELS: Record<string, string> = {
  clear: 'Clear (>=80%)',
  partial: 'Partial (40-79%)',
  weak: 'Weak (<40%)',
};

export default function MasteryPage() {
  const [masteryData, setMasteryData] = useState<MasteryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<'radar' | 'bar'>('radar');

  const fetchMastery = async () => {
    try {
      setLoading(true);
      const data = await apiClient.getMastery('default');
      setMasteryData(data);
    } catch (err) {
      console.error('Failed to load mastery data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMastery();
  }, []);

  const handleReset = async () => {
    if (window.confirm('Reset student mastery records for this session?')) {
      try {
        await apiClient.resetMastery('default');
        await fetchMastery();
      } catch (err) {
        console.error('Failed to reset mastery:', err);
      }
    }
  };

  const topics: MasteryItem[] = masteryData?.topic_mastery || [];
  const overallAvg = masteryData?.overall_readiness_pct || 0;
  const weakCount = masteryData?.weak_topics?.length || 0;
  const clearCount = masteryData?.clear_topics?.length || 0;

  const getOverallColor = () => {
    if (overallAvg >= 80) return '#16a34a';
    if (overallAvg >= 40) return '#d97706';
    return '#dc2626';
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      <div className={s.pageHeader}>
        <div>
          <h1>Student Competency & Mastery Map</h1>
          <p>
            Topic-level proficiency updated after each graded attempt using exponential moving average (EMA, α = 0.60).
          </p>
        </div>
        {topics.length > 0 && (
          <button className={s.btnGhost} onClick={handleReset} style={{ fontSize: '13px' }}>
            Reset Mastery Data
          </button>
        )}
      </div>

      {/* ── Summary cards ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 'var(--space-5)' }}>
        <div className="card" style={{ padding: 'var(--space-5)' }}>
          <p style={{ fontSize: '13px', color: '#64748b', marginBottom: '8px' }}>Overall Readiness Score</p>
          <div style={{ fontSize: '28px', fontWeight: 700, color: topics.length > 0 ? getOverallColor() : '#94a3b8' }}>
            {topics.length > 0 ? `${overallAvg}%` : '—'}
          </div>
        </div>
        <div className="card" style={{ padding: 'var(--space-5)' }}>
          <p style={{ fontSize: '13px', color: '#64748b', marginBottom: '8px' }}>Topics Cleared (80% or above)</p>
          <div style={{ fontSize: '28px', fontWeight: 700, color: '#16a34a' }}>
            {topics.length > 0 ? `${clearCount}/${topics.length}` : '—'}
          </div>
        </div>
        <div className="card" style={{ padding: 'var(--space-5)' }}>
          <p style={{ fontSize: '13px', color: '#64748b', marginBottom: '8px' }}>High-Yield Weak Areas (Under 40%)</p>
          <div style={{ fontSize: '28px', fontWeight: 700, color: weakCount > 0 ? '#dc2626' : '#94a3b8' }}>
            {topics.length > 0 ? weakCount : '—'}
          </div>
        </div>
      </div>

      {/* Recommended Focus Alert */}
      {masteryData?.recommended_focus && masteryData.recommended_focus.length > 0 && (
        <div
          style={{
            padding: '16px 20px',
            backgroundColor: '#fffbeb',
            border: '1px solid #fde68a',
            borderRadius: '8px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <div style={{ fontWeight: 600, color: '#92400e', marginBottom: '4px' }}>
              Adaptive Recommendation: High Priority Review
            </div>
            <div style={{ fontSize: '14px', color: '#b45309' }}>
              Your prediction weights will automatically boost practice questions in: <strong>{masteryData.recommended_focus.join(', ')}</strong>.
            </div>
          </div>
        </div>
      )}

      {/* ── Chart + toggle ── */}
      {topics.length > 0 ? (
        <div className="card" style={{ padding: '24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <h3>Topic Mastery Visualization</h3>
            <div style={{ display: 'flex', gap: '4px', background: '#f1f5f9', borderRadius: '6px', padding: '2px' }}>
              {(['radar', 'bar'] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  style={{
                    padding: '4px 12px',
                    borderRadius: '4px',
                    fontSize: '12px',
                    fontWeight: 600,
                    border: 'none',
                    cursor: 'pointer',
                    textTransform: 'capitalize',
                    background: view === v ? '#ffffff' : 'transparent',
                    color: view === v ? '#0f172a' : '#64748b',
                    boxShadow: view === v ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                  }}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>

          {view === 'radar' ? (
            <ResponsiveContainer width="100%" height={380}>
              <RadarChart data={topics.map((t) => ({ subject: t.unit.length > 20 ? t.unit.slice(0, 18) + '…' : t.unit, score: t.score_pct, fullMark: 100 }))}>
                <PolarGrid stroke="#e2e8f0" />
                <PolarAngleAxis dataKey="subject" tick={{ fontSize: 12, fill: '#334155' }} />
                <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fontSize: 10, fill: '#64748b' }} />
                <Tooltip contentStyle={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13 }} formatter={(v) => [`${v}%`, 'Score']} />
                <Radar name="Score" dataKey="score" stroke="#4f46e5" fill="#4f46e5" fillOpacity={0.25} strokeWidth={2.5} />
              </RadarChart>
            </ResponsiveContainer>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(300, topics.length * 45)}>
              <BarChart data={topics} layout="vertical" margin={{ left: 160, right: 30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 12, fill: '#64748b' }} />
                <YAxis type="category" dataKey="unit" tick={{ fontSize: 12, fill: '#334155' }} width={150} />
                <Tooltip contentStyle={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13 }} formatter={(v) => [`${v}%`, 'Score']} />
                <Bar dataKey="score_pct" radius={[0, 4, 4, 0]} barSize={22}>
                  {topics.map((t, i) => <Cell key={i} fill={BUCKET_COLORS[t.bucket]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      ) : null}

      {/* ── Topic breakdown table ── */}
      <div className="card">
        {loading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
            <span className="spinner" style={{ marginBottom: '12px' }} />
            <div>Loading competency profile...</div>
          </div>
        ) : topics.length > 0 ? (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Unit / Topic</th>
                  <th>Score</th>
                  <th style={{ width: 200 }}>Proficiency Bar</th>
                  <th>Competency Bucket</th>
                  <th>Practice Attempts</th>
                </tr>
              </thead>
              <tbody>
                {[...topics].sort((a, b) => a.score_pct - b.score_pct).map((topic) => (
                  <tr key={topic.unit}>
                    <td style={{ fontWeight: 600, color: '#0f172a' }}>{topic.unit}</td>
                    <td style={{ fontWeight: 700, color: BUCKET_COLORS[topic.bucket] }}>{topic.score_pct.toFixed(0)}%</td>
                    <td>
                      <div style={{ height: 6, background: '#f1f5f9', borderRadius: '4px', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${topic.score_pct}%`, background: BUCKET_COLORS[topic.bucket], borderRadius: '4px' }} />
                      </div>
                    </td>
                    <td>
                      <span className={`badge badge--${topic.bucket === 'clear' ? 'success' : topic.bucket === 'partial' ? 'warning' : 'danger'}`}>
                        {BUCKET_LABELS[topic.bucket]}
                      </span>
                    </td>
                    <td style={{ color: '#64748b' }}>{topic.attempt_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className={s.empty}>
            <div className={s.emptyIcon}>
              <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round">
                <path d="M12 2a4 4 0 014 4v1a4 4 0 01-1.38 3.02A5 5 0 0119 14.5V16a4 4 0 01-4 4h-1v2" />
                <path d="M12 2a4 4 0 00-4 4v1a4 4 0 001.38 3.02A5 5 0 005 14.5V16a4 4 0 004 4h1" />
                <line x1="12" y1="2" x2="12" y2="22" />
              </svg>
            </div>
            <h3>No mastery profile data yet</h3>
            <p>Complete predicted paper practice attempts to generate your topic competency profile.</p>
          </div>
        )}
      </div>
    </div>
  );
}
