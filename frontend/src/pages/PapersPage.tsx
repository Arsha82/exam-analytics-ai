import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import styles from './PapersPage.module.css';
import { apiClient, type Paper, type PipelineEvent } from '../api/client';

interface SelectedFile {
  file: File;
  id: string;
}

const STATUS_MAP: Record<string, { label: string; className: string }> = {
  pending:      { label: 'Pending',      className: 'badge badge--neutral' },
  processing:   { label: 'Processing',   className: 'badge badge--info' },
  completed:    { label: 'Completed',    className: 'badge badge--success' },
  needs_review: { label: 'Needs Review', className: 'badge badge--warning' },
  failed:       { label: 'Failed',       className: 'badge badge--danger' },
};

export default function PapersPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<SelectedFile[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [subject, setSubject] = useState('');
  const [year, setYear] = useState(new Date().getFullYear());
  const [totalMarks, setTotalMarks] = useState(100);
  const [uploading, setUploading] = useState(false);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [activePipelineMsg, setActivePipelineMsg] = useState<string | null>(null);

  const [sortField, setSortField] = useState<'year' | 'subject' | 'created_at'>('year');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const fetchPapers = async () => {
    try {
      setLoading(true);
      const data = await apiClient.getPapers();
      setPapers(data.papers);
    } catch (err) {
      console.error('Failed to fetch papers:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPapers();

    const ws = apiClient.createPipelineWebSocket((event: PipelineEvent) => {
      setActivePipelineMsg(`${event.agent} [${event.stage}]: ${event.detail} (${event.progress}%)`);
      if (event.progress === 100 || event.stage === 'complete') {
        fetchPapers();
        setTimeout(() => setActivePipelineMsg(null), 4000);
      }
    });

    return () => {
      ws.close();
    };
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const droppedFiles = Array.from(e.dataTransfer.files).filter(
      (f) =>
        f.type === 'application/pdf' ||
        f.type.startsWith('image/') ||
        f.name.toLowerCase().endsWith('.zip') ||
        f.type === 'application/zip' ||
        f.type === 'application/x-zip-compressed'
    );
    addFiles(droppedFiles);
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addFiles(Array.from(e.target.files));
  };

  const addFiles = (newFiles: File[]) => {
    setFiles((prev) => [
      ...prev,
      ...newFiles.map((f) => ({ file: f, id: crypto.randomUUID() })),
    ]);
  };

  const removeFile = (id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  };

  const handleUpload = async () => {
    if (!subject.trim() || files.length === 0) return;
    setUploading(true);

    for (const { file } of files) {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('subject', subject);
      formData.append('year', String(year));
      formData.append('total_marks', String(totalMarks));

      try {
        await apiClient.uploadPaper(formData);
      } catch (err) {
        console.error('Upload failed:', err);
      }
    }

    setFiles([]);
    setUploading(false);
    await fetchPapers();
  };

  const handleRerunOcr = async (paperId: string) => {
    try {
      await apiClient.rerunOcr(paperId);
      await fetchPapers();
    } catch (err) {
      console.error('Failed to rerun OCR:', err);
    }
  };

  const handleDeletePaper = async (paperId: string) => {
    if (window.confirm('Are you sure you want to delete this paper and all its extracted questions?')) {
      try {
        await apiClient.deletePaper(paperId);
        await fetchPapers();
      } catch (err) {
        console.error('Failed to delete paper:', err);
      }
    }
  };

  const handleSort = (field: typeof sortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('desc');
    }
  };

  const sortedPapers = [...papers].sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1;
    if (sortField === 'year') return (a.year - b.year) * dir;
    if (sortField === 'subject') return a.subject.localeCompare(b.subject) * dir;
    return (new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) * dir;
  });

  return (
    <div className={styles.papers}>
      {/* ── Header ── */}
      <div className={styles.papers__header}>
        <div>
          <h1>Exam Papers</h1>
          <p>Upload scanned papers (PDF/images). Unlimited-OCR & gemma4:12b extract and correlate questions automatically.</p>
        </div>
      </div>

      {/* ── Live Pipeline Banner ── */}
      {activePipelineMsg && (
        <div
          style={{
            marginBottom: '16px',
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
          <span><strong>Pipeline Active:</strong> {activePipelineMsg}</span>
        </div>
      )}

      {/* ── Drop zone ── */}
      <div
        className={`${styles.dropzone} ${dragActive ? styles['dropzone--active'] : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,image/*,.zip,application/zip,application/x-zip-compressed"
          multiple
          className={styles.dropzone__input}
          onChange={handleFileSelect}
        />
        <div className={styles.dropzone__icon}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="17,8 12,3 7,8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </div>
        <h3>Drop question papers, merged PDFs, or ZIP archives here</h3>
        <p>PDFs, multi-year merged collections, ZIP batches, or scanned images · Click to browse</p>
        <span style={{ fontSize: '11px', color: '#64748b', marginTop: '6px', display: 'inline-block' }}>
          ✨ Powered by Gemma 4 Intelligence for automatic exam boundary splitting &amp; ZIP auto-extraction
        </span>
      </div>

      {/* ── File list + upload form ── */}
      {files.length > 0 && (
        <div className="card animate-fade-in-up" style={{ padding: 'var(--space-5)', marginTop: '16px' }}>
          <div className={styles['file-list']}>
            {files.map(({ file, id }) => (
              <div key={id} className={styles['file-item']}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z" />
                  <polyline points="14,2 14,8 20,8" />
                </svg>
                <span className={styles['file-item__name']}>{file.name}</span>
                <span className={styles['file-item__size']}>{formatSize(file.size)}</span>
                <button className={styles['file-item__remove']} onClick={() => removeFile(id)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            ))}
          </div>

          <div className={styles['upload-form']}>
            <div className={styles['upload-form__field']}>
              <label>Subject</label>
              <input
                type="text"
                placeholder="e.g. Mathematics"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
              />
            </div>
            <div className={styles['upload-form__field']}>
              <label>Year</label>
              <input
                type="number"
                min={1990}
                max={2030}
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
              />
            </div>
            <div className={styles['upload-form__field']}>
              <label>Total Marks</label>
              <input
                type="number"
                min={1}
                value={totalMarks}
                onChange={(e) => setTotalMarks(Number(e.target.value))}
              />
            </div>
            <button
              className={`${styles.btn} ${styles['btn--primary']}`}
              onClick={handleUpload}
              disabled={!subject.trim() || uploading}
            >
              {uploading ? (
                <>
                  <span className="spinner" />
                  Uploading & Starting Agents...
                </>
              ) : (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <polyline points="17,8 12,3 7,8" /><line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                  Upload & Run Pipeline
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* ── Papers table ── */}
      <div className="card" style={{ marginTop: '24px' }}>
        {loading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
            <span className="spinner" style={{ marginBottom: '12px' }} />
            <div>Loading papers...</div>
          </div>
        ) : sortedPapers.length > 0 ? (
          <div className={styles['table-wrapper']}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th onClick={() => handleSort('subject')}>
                    Subject {sortField === 'subject' && (sortDir === 'asc' ? '↑' : '↓')}
                  </th>
                  <th onClick={() => handleSort('year')}>
                    Year {sortField === 'year' && (sortDir === 'asc' ? '↑' : '↓')}
                  </th>
                  <th>Marks</th>
                  <th>Questions</th>
                  <th>OCR Status</th>
                  <th onClick={() => handleSort('created_at')}>
                    Uploaded {sortField === 'created_at' && (sortDir === 'asc' ? '↑' : '↓')}
                  </th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedPapers.map((paper) => {
                  const status = STATUS_MAP[paper.ocr_status] || STATUS_MAP.pending;
                  return (
                    <tr key={paper.paper_id}>
                      <td className={styles.table__subject}>
                        <strong>{paper.subject}</strong>
                      </td>
                      <td>{paper.year}</td>
                      <td>{paper.total_marks}</td>
                      <td>
                        <span style={{ fontWeight: 600, color: '#3b82f6' }}>{paper.question_count}</span>
                      </td>
                      <td>
                        <span className={status.className}>{status.label}</span>
                        {paper.needs_review && (
                          <span
                            className="badge badge--warning"
                            style={{ marginLeft: '6px' }}
                            title="Flagged for mark mismatch or low OCR confidence"
                          >
                            Review
                          </span>
                        )}
                      </td>
                      <td style={{ color: 'var(--text-tertiary)', fontSize: 'var(--text-xs)' }}>
                        {new Date(paper.created_at).toLocaleDateString()}
                      </td>
                      <td>
                        <div className={styles.table__actions}>
                          <button
                            className={`${styles.btn} ${styles['btn--ghost']} ${styles['btn--sm']}`}
                            onClick={() => navigate(`/questions?subject=${encodeURIComponent(paper.subject)}&year=${paper.year}`)}
                          >
                            View Questions
                          </button>
                          <button
                            className={`${styles.btn} ${styles['btn--ghost']} ${styles['btn--sm']}`}
                            onClick={() => handleRerunOcr(paper.paper_id)}
                            title="Re-run OCR and structuring"
                          >
                            Re-Run
                          </button>
                          <button
                            className={`${styles.btn} ${styles['btn--danger']} ${styles['btn--sm']}`}
                            onClick={() => handleDeletePaper(paper.paper_id)}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className={styles.empty}>
            <div className={styles.empty__icon}>
              <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round">
                <path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z" />
                <polyline points="14,2 14,8 20,8" />
                <line x1="9" y1="13" x2="15" y2="13" />
                <line x1="9" y1="17" x2="13" y2="17" />
              </svg>
            </div>
            <h3>No papers uploaded yet</h3>
            <p>Drag and drop your scanned question papers above to begin extracting and analyzing questions.</p>
          </div>
        )}
      </div>
    </div>
  );
}
