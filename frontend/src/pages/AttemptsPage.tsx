import { useCallback, useEffect, useRef, useState } from 'react';
import s from '../design/shared.module.css';
import { apiClient, type Attempt, type PredictedPaper, type PipelineEvent } from '../api/client';

export default function AttemptsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [paperId, setPaperId] = useState('');
  const [availablePapers, setAvailablePapers] = useState<PredictedPaper[]>([]);
  const [uploading, setUploading] = useState(false);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [selectedAttempt, setSelectedAttempt] = useState<Attempt | null>(null);
  const [loading, setLoading] = useState(true);
  const [activePipelineMsg, setActivePipelineMsg] = useState<string | null>(null);

  const fetchAttempts = async () => {
    try {
      setLoading(true);
      const data = await apiClient.getAttempts();
      setAttempts(data.attempts);
    } catch (err) {
      console.error('Failed to load attempts:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAttempts();

    // Load available predicted papers for the select dropdown
    apiClient.getPredictions().then((data) => {
      setAvailablePapers(data.predictions);
      if (data.predictions.length > 0) {
        setPaperId(data.predictions[0].predicted_paper_id);
      }
    }).catch(console.error);

    const ws = apiClient.createPipelineWebSocket((event: PipelineEvent) => {
      if (event.agent === 'EvaluationAgent' || event.stage === 'evaluation') {
        setActivePipelineMsg(`${event.detail} (${event.progress}%)`);
        if (event.progress === 100 || event.stage === 'complete') {
          fetchAttempts();
          setTimeout(() => setActivePipelineMsg(null), 4000);
        }
      }
    });

    return () => {
      ws.close();
    };
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) setSelectedFile(files[0]);
  }, []);

  const handleUpload = async () => {
    if (!selectedFile || !paperId.trim()) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('predicted_paper_id', paperId);
      formData.append('student_id', 'default');

      await apiClient.uploadAttempt(formData);
      setSelectedFile(null);
      await fetchAttempts();
    } catch (err) {
      console.error('Upload failed:', err);
    } finally {
      setUploading(false);
    }
  };

  const handleSelectAttempt = async (attemptId: string) => {
    try {
      const full = await apiClient.getAttempt(attemptId);
      setSelectedAttempt(full);
    } catch (err) {
      console.error('Failed to load attempt details:', err);
    }
  };

  const getScoreColor = (pct: number) => {
    if (pct >= 80) return '#16a34a'; // green
    if (pct >= 40) return '#d97706'; // amber
    return '#dc2626'; // red
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      <div className={s.pageHeader}>
        <div>
          <h1>Student Attempts & Automated Grading</h1>
          <p>Digitize handwritten or typed answer sheets and evaluate against question checklist rubrics using gemma4:12b.</p>
        </div>
      </div>

      {/* Live Pipeline Banner */}
      {activePipelineMsg && (
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: '#eff6ff',
            border: '1px solid #bfdbfe',
            borderRadius: '8px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            color: '#1e40af',
            fontSize: '14px',
          }}
        >
          <span className="spinner" style={{ width: '16px', height: '16px', borderWidth: '2px' }} />
          <span><strong>Grading in Progress:</strong> {activePipelineMsg}</span>
        </div>
      )}

      {/* Upload */}
      <div className="card" style={{ padding: 'var(--space-5)' }}>
        <h3 style={{ marginBottom: 'var(--space-4)', fontSize: '16px', fontWeight: 600 }}>Submit Answer Sheet for Evaluation</h3>
        <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
          {/* File drop */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            style={{
              flex: 1, minWidth: 260, padding: '24px 16px',
              border: `2px dashed ${dragActive ? '#3b82f6' : '#cbd5e1'}`,
              borderRadius: '8px', textAlign: 'center', cursor: 'pointer',
              backgroundColor: dragActive ? '#eff6ff' : '#f8fafc',
            }}
          >
            <input ref={fileInputRef} type="file" accept=".pdf,image/*" style={{ display: 'none' }} onChange={(e) => e.target.files && setSelectedFile(e.target.files[0])} />
            {selectedFile ? (
              <div>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2" strokeLinecap="round" style={{ margin: '0 auto 8px' }}>
                  <polyline points="20,6 9,17 4,12" />
                </svg>
                <p style={{ fontSize: '14px', fontWeight: 600, color: '#0f172a' }}>{selectedFile.name}</p>
                <p style={{ fontSize: '12px', color: '#64748b' }}>{(selectedFile.size / 1048576).toFixed(1)} MB</p>
              </div>
            ) : (
              <div>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="1.5" strokeLinecap="round" style={{ margin: '0 auto 8px' }}>
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="17,8 12,3 7,8" /><line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                <p style={{ fontSize: '14px', color: '#334155', fontWeight: 500 }}>Drop answer sheet (PDF or image)</p>
                <p style={{ fontSize: '12px', color: '#94a3b8' }}>or click to browse files</p>
              </div>
            )}
          </div>

          {/* Paper selector + submit */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', minWidth: 260 }}>
            <div className={s.field}>
              <label style={{ fontSize: '13px', fontWeight: 600, marginBottom: '4px' }}>Target Predicted Paper</label>
              {availablePapers.length > 0 ? (
                <select
                  className={s.select}
                  value={paperId}
                  onChange={(e) => setPaperId(e.target.value)}
                  style={{ width: '100%', fontWeight: 500 }}
                >
                  {availablePapers.map((p) => (
                    <option key={p.predicted_paper_id} value={p.predicted_paper_id}>
                      {p.subject} (v{p.variant}, {p.target_marks}m) - {p.predicted_paper_id.slice(-8)}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className={s.input}
                  placeholder="Enter predicted paper ID"
                  value={paperId}
                  onChange={(e) => setPaperId(e.target.value)}
                />
              )}
            </div>

            <button
              className={s.btnPrimary}
              onClick={handleUpload}
              disabled={!selectedFile || !paperId.trim() || uploading}
              style={{ marginTop: '8px' }}
            >
              {uploading ? (
                <><span className="spinner" /> Evaluating with Rubric...</>
              ) : (
                <>Submit & Grade Answer Sheet</>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* ── Detail view ── */}
      {selectedAttempt ? (
        <div className="animate-fade-in-up">
          <button className={s.btnGhost} onClick={() => setSelectedAttempt(null)} style={{ marginBottom: '16px' }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12,19 5,12 12,5" />
            </svg>
            Back to attempts list
          </button>

          <div className="card" style={{ padding: '24px' }}>
            {/* Summary bar */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', paddingBottom: '16px', borderBottom: '1px solid #e2e8f0' }}>
              <div>
                <h2>Grading Result Breakdown</h2>
                <p style={{ fontSize: '13px', color: '#64748b', marginTop: '4px' }}>
                  Paper: {selectedAttempt.predicted_paper_id} · Submitted {new Date(selectedAttempt.submitted_at).toLocaleDateString()}
                </p>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: '28px', fontWeight: 700, color: selectedAttempt.total_marks_awarded != null && selectedAttempt.total_max_marks ? getScoreColor((selectedAttempt.total_marks_awarded / selectedAttempt.total_max_marks) * 100) : '#1e293b' }}>
                  {selectedAttempt.total_marks_awarded ?? '—'} / {selectedAttempt.total_max_marks ?? '—'}
                </div>
                {selectedAttempt.total_marks_awarded != null && selectedAttempt.total_max_marks && (
                  <span style={{ fontSize: '14px', fontWeight: 600, color: '#64748b' }}>
                    Score: {((selectedAttempt.total_marks_awarded / selectedAttempt.total_max_marks) * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            </div>

            {/* Per-question scores */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {selectedAttempt.scores?.map((score) => {
                const pct = (score.marks_awarded / score.max_marks) * 100;
                return (
                  <div key={score.question_id} style={{ padding: '16px', border: '1px solid #e2e8f0', borderRadius: '8px', backgroundColor: '#ffffff' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 700, fontSize: '15px', color: '#0f172a' }}>Question {score.question_id}</span>
                        {score.low_confidence && <span className="badge badge--warning">Low Confidence</span>}
                      </div>
                      <span style={{ fontWeight: 700, fontSize: '16px', color: getScoreColor(pct) }}>
                        {score.marks_awarded} / {score.max_marks} Marks
                      </span>
                    </div>

                    {/* Progress bar */}
                    <div style={{ height: 6, background: '#f1f5f9', borderRadius: '4px', marginBottom: '10px', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${pct}%`, background: getScoreColor(pct), borderRadius: '4px' }} />
                    </div>

                    <p style={{ fontSize: '14px', color: '#334155', lineHeight: 1.5, margin: '0 0 8px 0' }}>
                      <strong>Examiner Feedback:</strong> {score.reasoning}
                    </p>

                    {score.missing_points && score.missing_points.length > 0 && (
                      <div style={{ marginTop: '8px', padding: '10px', background: '#fef2f2', borderRadius: '6px', border: '1px solid #fee2e2' }}>
                        <span style={{ fontSize: '13px', fontWeight: 600, color: '#dc2626' }}>Points Omitted from Rubric:</span>
                        <ul style={{ marginTop: '4px', paddingLeft: '20px', listStyle: 'disc' }}>
                          {score.missing_points.map((mp, i) => (
                            <li key={i} style={{ fontSize: '13px', color: '#991b1b' }}>{mp}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : (
        /* ── Attempt list ── */
        <div className="card">
          {loading ? (
            <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
              <span className="spinner" style={{ marginBottom: '12px' }} />
              <div>Loading attempts...</div>
            </div>
          ) : attempts.length > 0 ? (
            <div className={s.tableWrap}>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>Attempt ID</th>
                    <th>Target Paper</th>
                    <th>Marks Awarded</th>
                    <th>Status</th>
                    <th>Submission Date</th>
                  </tr>
                </thead>
                <tbody>
                  {attempts.map((a) => {
                    const pct = a.total_marks_awarded != null && a.total_max_marks ? (a.total_marks_awarded / a.total_max_marks) * 100 : null;
                    return (
                      <tr key={a.attempt_id} onClick={() => handleSelectAttempt(a.attempt_id)} style={{ cursor: 'pointer' }}>
                        <td style={{ fontWeight: 600, color: '#2563eb' }}>{a.attempt_id}</td>
                        <td>{a.predicted_paper_id}</td>
                        <td>
                          {pct !== null ? (
                            <span style={{ fontWeight: 700, color: getScoreColor(pct) }}>
                              {a.total_marks_awarded} / {a.total_max_marks} ({pct.toFixed(0)}%)
                            </span>
                          ) : '—'}
                        </td>
                        <td>
                          <span className={a.ocr_status === 'completed' ? 'badge badge--success' : a.ocr_status === 'processing' ? 'badge badge--info' : 'badge badge--neutral'}>
                            {a.ocr_status}
                          </span>
                        </td>
                        <td style={{ fontSize: '13px', color: '#64748b' }}>{new Date(a.submitted_at).toLocaleDateString()}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className={s.empty}>
              <div className={s.emptyIcon}>
                <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round">
                  <path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4L16.5 3.5z" />
                </svg>
              </div>
              <h3>No student attempts evaluated yet</h3>
              <p>Generate a predicted paper, then upload your handwritten or typed attempt to receive rubric-based automated grading.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
