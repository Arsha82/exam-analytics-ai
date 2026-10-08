import { useEffect, useState } from 'react';
import s from '../design/shared.module.css';
import { apiClient, type PredictedPaper, type PredictedQuestion } from '../api/client';

export default function PredictionsPage() {
  const [papers, setPapers] = useState<PredictedPaper[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [genSubject, setGenSubject] = useState('Mathematics');
  const [availableSubjects, setAvailableSubjects] = useState<string[]>(['Mathematics']);
  const [genMarks, setGenMarks] = useState(100);
  const [genVariants, setGenVariants] = useState(2);
  const [selectedPaper, setSelectedPaper] = useState<PredictedPaper | null>(null);
  const [showRubric, setShowRubric] = useState<string | null>(null);

  const fetchPredictions = async () => {
    try {
      setLoading(true);
      const data = await apiClient.getPredictions();
      setPapers(data.predictions);
    } catch (err) {
      console.error('Failed to load predictions:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPredictions();

    // Populate available subjects from existing papers
    apiClient.getPapers().then((data) => {
      const subs = [...new Set(data.papers.map((p) => p.subject))];
      if (subs.length > 0) {
        setAvailableSubjects(subs);
        setGenSubject(subs[0]);
      }
    }).catch(console.error);
  }, []);

  const handleGenerate = async () => {
    if (!genSubject.trim()) return;
    setGenerating(true);
    try {
      await apiClient.generatePrediction(genSubject, genMarks, genVariants);
      await fetchPredictions();
    } catch (err) {
      console.error('Prediction generation failed:', err);
    } finally {
      setGenerating(false);
    }
  };

  const handleSelectPaper = async (paperId: string) => {
    try {
      const full = await apiClient.getPrediction(paperId);
      setSelectedPaper(full);
    } catch (err) {
      console.error('Failed to load paper details:', err);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      <div className={s.pageHeader}>
        <div>
          <h1>Predicted Question Papers</h1>
          <p>Synthesizes weighted examination papers with checklist rubrics using topic frequencies and trend multipliers.</p>
        </div>
      </div>

      {/* ── Generate form ── */}
      <div className="card" style={{ padding: 'var(--space-5)' }}>
        <h3 style={{ marginBottom: 'var(--space-4)', fontSize: 'var(--text-base)' }}>Synthesize New Predicted Paper</h3>
        <div className={s.filters}>
          <div className={s.field}>
            <label>Subject</label>
            <select
              className={s.select}
              value={genSubject}
              onChange={(e) => setGenSubject(e.target.value)}
              style={{ fontWeight: 600 }}
            >
              {availableSubjects.map((sub) => (
                <option key={sub} value={sub}>{sub}</option>
              ))}
            </select>
          </div>
          <div className={s.field}>
            <label>Target Marks</label>
            <input
              className={s.input}
              type="number"
              min={10}
              value={genMarks}
              onChange={(e) => setGenMarks(Number(e.target.value))}
              style={{ width: 110 }}
            />
          </div>
          <div className={s.field}>
            <label>Alternate Variants</label>
            <select className={s.select} value={genVariants} onChange={(e) => setGenVariants(Number(e.target.value))}>
              <option value={1}>1 paper (Primary)</option>
              <option value={2}>2 papers (v1 + alternate v2)</option>
              <option value={3}>3 papers (v1, v2, v3)</option>
            </select>
          </div>
          <button className={s.btnPrimary} onClick={handleGenerate} disabled={!genSubject.trim() || generating} style={{ marginTop: 18 }}>
            {generating ? (
              <><span className="spinner" /> Synthesizing with gemma4:12b...</>
            ) : (
              <>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />
                </svg>
                Generate Predicted Paper
              </>
            )}
          </button>
        </div>
      </div>

      {/* ── Paper list / detail split ── */}
      {selectedPaper ? (
        <div className="animate-fade-in-up">
          <button className={s.btnGhost} onClick={() => setSelectedPaper(null)} style={{ marginBottom: 'var(--space-4)' }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12,19 5,12 12,5" />
            </svg>
            Back to papers list
          </button>

          <div className="card" style={{ padding: 'var(--space-6)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-5)' }}>
              <div>
                <h2>{selectedPaper.subject} — Variant {selectedPaper.variant}</h2>
                <p style={{ fontSize: '13px', color: '#64748b', marginTop: '4px' }}>
                  {selectedPaper.target_marks} marks · {selectedPaper.questions?.length || 0} questions · Generated {new Date(selectedPaper.generated_at).toLocaleDateString()}
                </p>
              </div>
              <a
                href={`http://localhost:8000/api/predictions/${selectedPaper.predicted_paper_id}/download`}
                target="_blank"
                rel="noreferrer"
                className={s.btnPrimary}
                style={{ textDecoration: 'none' }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7,10 12,15 17,10" /><line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                Print / Export Paper
              </a>
            </div>

            {/* Question list */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {selectedPaper.questions?.map((q: PredictedQuestion) => (
                <div key={q.question_no} style={{ padding: '16px', border: '1px solid #e2e8f0', borderRadius: '8px', backgroundColor: '#ffffff' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px' }}>
                        <span style={{ fontWeight: 700, color: '#0f172a', fontSize: '14px' }}>Q{q.question_no}</span>
                        <span className={s.tag}>{q.unit}</span>
                        <span style={{ fontSize: '12px', fontWeight: 600, color: '#475569' }}>{q.marks} marks</span>
                      </div>
                      <p style={{ fontSize: '15px', color: '#1e293b', lineHeight: 1.6, margin: '0 0 8px 0' }}>{q.text}</p>
                    </div>
                    {q.rubric && q.rubric.length > 0 && (
                      <button
                        className={`${s.btnGhost} ${s.btnSm}`}
                        onClick={() => setShowRubric(showRubric === q.question_no ? null : q.question_no)}
                      >
                        {showRubric === q.question_no ? 'Hide Rubric' : 'View Rubric'}
                      </button>
                    )}
                  </div>

                  {/* Rubric checklist */}
                  {showRubric === q.question_no && q.rubric && (
                    <div style={{ marginTop: '12px', padding: '12px', background: '#f8fafc', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
                      <div style={{ fontSize: '12px', fontWeight: 700, color: '#334155', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        Grading Checklist Rubric ({q.marks} Marks)
                      </div>
                      {q.rubric.map((item, i) => (
                        <div
                          key={i}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            padding: '6px 0',
                            fontSize: '13px',
                            color: '#334155',
                            borderBottom: i < q.rubric!.length - 1 ? '1px solid #e2e8f0' : 'none',
                          }}
                        >
                          <span>☐ {item.point}</span>
                          <span style={{ fontWeight: 600, color: '#0284c7' }}>{item.weight}m</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div>
          {loading ? (
            <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
              <span className="spinner" style={{ marginBottom: '12px' }} />
              <div>Loading predicted papers...</div>
            </div>
          ) : papers.length > 0 ? (
            <div className={s.gridAuto}>
              {papers.map((paper) => (
                <div
                  key={paper.predicted_paper_id}
                  className="card pressable"
                  style={{ padding: 'var(--space-5)', cursor: 'pointer', border: '1px solid #e2e8f0' }}
                  onClick={() => handleSelectPaper(paper.predicted_paper_id)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <h3 style={{ fontSize: '16px', fontWeight: 600 }}>{paper.subject}</h3>
                    <span className={s.tag}>v{paper.variant}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '16px', fontSize: '13px', color: '#64748b' }}>
                    <span>{paper.target_marks} marks</span>
                    <span>{paper.question_count || 'Multi'} questions</span>
                  </div>
                  <p style={{ fontSize: '12px', color: '#94a3b8', marginTop: '10px' }}>
                    Generated {new Date(paper.generated_at).toLocaleDateString()}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <div className="card">
              <div className={s.empty}>
                <div className={s.emptyIcon}>
                  <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round">
                    <circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" />
                  </svg>
                </div>
                <h3>No predictions generated</h3>
                <p>Generate your first predicted paper using the form above. Predictions are weighted by topic frequency, year-over-year trends, and your mastery profile.</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
