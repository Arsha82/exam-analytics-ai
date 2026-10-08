import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line, Legend, Cell } from 'recharts';
import s from '../design/shared.module.css';
import { apiClient, type AnalysisResults } from '../api/client';

const COLORS_HEX = ['#4f46e5', '#16a34a', '#d97706', '#dc2626', '#2563eb', '#9333ea', '#0d9488', '#ea580c'];

type TabKey = 'frequency' | 'trends' | 'clusters' | 'twisted';

interface FrequencyItem {
  unit: string;
  count: number;
  pct: number;
  marks: number;
  marksPct: number;
}

interface TrendRow {
  year: number;
  [unit: string]: number;
}

export default function AnalysisPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('frequency');
  const [freqMode, setFreqMode] = useState<'count' | 'marks'>('count');
  const [subject, setSubject] = useState('Mathematics');
  const [availableSubjects, setAvailableSubjects] = useState<string[]>(['Mathematics']);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const [frequency, setFrequency] = useState<FrequencyItem[]>([]);
  const [trendData, setTrendData] = useState<TrendRow[]>([]);
  const [trendUnits, setTrendUnits] = useState<string[]>([]);
  const [clusters, setClusters] = useState<{ label: string; count: number; question_ids: string[] }[]>([]);
  const [twistedPairs, setTwistedPairs] = useState<any[]>([]);

  // Fetch available subjects
  useEffect(() => {
    apiClient.getPapers().then((data) => {
      const subs = [...new Set(data.papers.map((p) => p.subject))];
      if (subs.length > 0) {
        setAvailableSubjects(subs);
        setSubject(subs[0]);
      }
    }).catch(console.error);
  }, []);

  const loadAnalysis = async (sub: string) => {
    try {
      setLoading(true);
      const data: AnalysisResults = await apiClient.getAnalysisSummary(sub);

      // 1. Frequency & Marks
      const marksMap = new Map(data.mark_weights.map((m) => [m.unit, m]));
      const freqItems: FrequencyItem[] = data.frequency.map((f) => {
        const m = marksMap.get(f.unit);
        return {
          unit: f.unit,
          count: f.count,
          pct: f.pct_of_total,
          marks: m ? m.total_marks : 0,
          marksPct: m ? m.pct_of_total_marks : 0,
        };
      });
      setFrequency(freqItems);

      // 2. Trends
      const unitsList = [...new Set(data.trends.map((t) => t.unit))];
      setTrendUnits(unitsList);

      const yearsMap = new Map<number, TrendRow>();
      data.trends.forEach((t) => {
        if (!yearsMap.has(t.year)) {
          yearsMap.set(t.year, { year: t.year });
        }
        const row = yearsMap.get(t.year)!;
        row[t.unit] = t.mark_share_pct;
      });
      const rows = Array.from(yearsMap.values()).sort((a, b) => a.year - b.year);
      setTrendData(rows);

      // 3. Clusters
      setClusters(data.clusters.map((c) => ({
        label: c.label,
        count: c.question_ids.length,
        question_ids: c.question_ids,
      })));

      // 4. Twisted / Duplicate Pairs
      setTwistedPairs(data.twisted_pairs);
    } catch (err) {
      console.error('Failed to load analysis:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (subject) {
      loadAnalysis(subject);
    }
  }, [subject]);

  const handleRunAnalysis = async () => {
    try {
      setRunning(true);
      await apiClient.runAnalysis(subject);
      await loadAnalysis(subject);
    } catch (err) {
      console.error('Failed to run analysis:', err);
    } finally {
      setRunning(false);
    }
  };

  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: 'frequency', label: 'Frequency & Weights' },
    { key: 'trends', label: 'Yearly Trend Slopes' },
    { key: 'clusters', label: 'Question Types' },
    { key: 'twisted', label: 'Twisted & Near Duplicates', count: twistedPairs.length },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      <div className={s.pageHeader}>
        <div>
          <h1>Pattern Intelligence & Statistical Analytics</h1>
          <p>Linear regression trends, topic weightages, and semantic duplicate detection computed across exam papers.</p>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <select
            className={s.select}
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            style={{ fontWeight: 600 }}
          >
            {availableSubjects.map((sub) => (
              <option key={sub} value={sub}>{sub}</option>
            ))}
          </select>

          <button className={s.btnPrimary} onClick={handleRunAnalysis} disabled={running}>
            {running ? (
              <>
                <span className="spinner" /> Computing...
              </>
            ) : (
              <>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <polyline points="1,4 1,10 7,10" /><path d="M3.51 15a9 9 0 102.13-9.36L1 10" />
                </svg>
                Re-Run Analysis
              </>
            )}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className={s.tabs}>
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={activeTab === tab.key ? s.tabActive : s.tab}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
            {tab.count !== undefined && tab.count > 0 && (
              <span className="badge badge--warning" style={{ marginLeft: 6 }}>{tab.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="animate-fade-in-up">
        {loading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
            <span className="spinner" style={{ marginBottom: '12px' }} />
            <div>Running statistical analysis...</div>
          </div>
        ) : activeTab === 'frequency' ? (
          <div className="card" style={{ padding: 'var(--space-6)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-5)' }}>
              <h3>Topic {freqMode === 'count' ? 'Question Count' : 'Total Mark Weight'} Distribution</h3>
              <div style={{ display: 'flex', gap: 'var(--space-1)', background: 'var(--surface-2)', borderRadius: 'var(--radius-md)', padding: 2 }}>
                <button
                  onClick={() => setFreqMode('count')}
                  style={{
                    padding: 'var(--space-1) var(--space-3)', borderRadius: 'var(--radius-sm)', fontSize: 'var(--text-xs)', fontWeight: 500, border: 'none', cursor: 'pointer',
                    background: freqMode === 'count' ? 'var(--surface-1)' : 'transparent',
                    color: freqMode === 'count' ? 'var(--text-primary)' : 'var(--text-tertiary)',
                  }}
                >Questions</button>
                <button
                  onClick={() => setFreqMode('marks')}
                  style={{
                    padding: 'var(--space-1) var(--space-3)', borderRadius: 'var(--radius-sm)', fontSize: 'var(--text-xs)', fontWeight: 500, border: 'none', cursor: 'pointer',
                    background: freqMode === 'marks' ? 'var(--surface-1)' : 'transparent',
                    color: freqMode === 'marks' ? 'var(--text-primary)' : 'var(--text-tertiary)',
                  }}
                >Marks</button>
              </div>
            </div>

            {frequency.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(300, frequency.length * 48)}>
                <BarChart data={frequency} layout="vertical" margin={{ left: 160, right: 30, top: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 12, fill: '#64748b' }} />
                  <YAxis type="category" dataKey="unit" tick={{ fontSize: 12, fill: '#1e293b' }} width={150} />
                  <Tooltip
                    contentStyle={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13, boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)' }}
                    formatter={(value) => [`${value}${freqMode === 'count' ? ' questions' : ' marks'}`, '']}
                  />
                  <Bar dataKey={freqMode === 'count' ? 'count' : 'marks'} radius={[0, 4, 4, 0]} barSize={26}>
                    {frequency.map((_, i) => (
                      <Cell key={i} fill={COLORS_HEX[i % COLORS_HEX.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className={s.empty}>
                <h3>No frequency data available</h3>
                <p>Upload exam papers for {subject} to compute weightage distributions.</p>
              </div>
            )}
          </div>
        ) : activeTab === 'trends' ? (
          <div className="card" style={{ padding: 'var(--space-6)' }}>
            <h3 style={{ marginBottom: 'var(--space-2)' }}>Year-over-Year Unit Mark Share (% Trend)</h3>
            <p style={{ fontSize: '13px', color: '#64748b', marginBottom: '24px' }}>
              Tracks whether a topic's share of total exam marks is rising (multiplier 1.25x), stable (1.0x), or declining (0.80x).
            </p>
            {trendData.length > 0 ? (
              <ResponsiveContainer width="100%" height={400}>
                <LineChart data={trendData} margin={{ left: 10, right: 30, top: 10, bottom: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="year" tick={{ fontSize: 12, fill: '#64748b' }} />
                  <YAxis tick={{ fontSize: 12, fill: '#64748b' }} unit="%" />
                  <Tooltip contentStyle={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {trendUnits.map((unit, i) => (
                    <Line
                      key={unit}
                      type="monotone"
                      dataKey={unit}
                      stroke={COLORS_HEX[i % COLORS_HEX.length]}
                      strokeWidth={2.5}
                      dot={{ r: 4 }}
                      activeDot={{ r: 6 }}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className={s.empty}>
                <h3>No multi-year trend data yet</h3>
                <p>Upload papers from 2 or more exam years to visualize trend slopes.</p>
              </div>
            )}
          </div>
        ) : activeTab === 'clusters' ? (
          <div>
            {clusters.length > 0 ? (
              <div className={s.gridAuto}>
                {clusters.map((cluster, i) => (
                  <div key={cluster.label} className="card" style={{ padding: 'var(--space-5)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
                      <div style={{ width: 12, height: 12, borderRadius: 'var(--radius-sm)', background: COLORS_HEX[i % COLORS_HEX.length] }} />
                      <h3 style={{ fontSize: 'var(--text-base)', textTransform: 'capitalize' }}>{cluster.label}</h3>
                      <span className={s.tag}>{cluster.count}</span>
                    </div>
                    <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-tertiary)' }}>
                      Questions categorized under {cluster.label.toLowerCase()} based on keywords and mathematical notation.
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="card">
                <div className={s.empty}>
                  <h3>No clusters computed</h3>
                  <p>Questions will be categorized as derivations, numericals, diagrams, and definitions.</p>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div>
            {twistedPairs.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                {twistedPairs.map((pair, i) => (
                  <div key={i} className="card" style={{ padding: 'var(--space-5)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-3)' }}>
                      <span className={pair.verdict === 'near-duplicate' ? 'badge badge--danger' : 'badge badge--warning'}>
                        {pair.verdict === 'near-duplicate' ? 'Near Duplicate (>=92%)' : 'Twisted Rewording (80-91%)'}
                      </span>
                      <span style={{ fontSize: '13px', fontWeight: 600, color: '#475569' }}>
                        Cosine Similarity: {(pair.similarity * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
                      <div style={{ padding: '12px', background: '#f8fafc', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
                        <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', marginBottom: '4px' }}>
                          Question ID: {pair.question_id_a}
                        </div>
                        <p style={{ fontSize: '14px', color: '#1e293b', margin: 0 }}>{pair.reasoning || pair.question_id_a}</p>
                      </div>
                      <div style={{ padding: '12px', background: '#f8fafc', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
                        <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', marginBottom: '4px' }}>
                          Question ID: {pair.question_id_b}
                        </div>
                        <p style={{ fontSize: '14px', color: '#1e293b', margin: 0 }}>Identified variant in paired exam session.</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="card">
                <div className={s.empty}>
                  <div className={s.emptyIcon}>
                    <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round">
                      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                    </svg>
                  </div>
                  <h3>No duplicate questions detected</h3>
                  <p>When multiple papers are uploaded, the vector similarity engine detects near-duplicates and twisted concept rewordings.</p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
