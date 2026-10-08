import { useEffect, useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import s from '../design/shared.module.css';
import { apiClient, type Question } from '../api/client';

export default function QuestionsPage() {
  const [searchParams] = useSearchParams();
  const initialSubject = searchParams.get('subject') || '';
  const initialYear = searchParams.get('year') || '';

  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterYear, setFilterYear] = useState<string>(initialYear);
  const [filterUnit, setFilterUnit] = useState<string>('');
  const [filterReview, setFilterReview] = useState<string>('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const fetchQuestions = async () => {
    try {
      setLoading(true);
      const data = await apiClient.getQuestions({
        subject: initialSubject || undefined,
        limit: 200,
      });
      setQuestions(data.questions);
    } catch (err) {
      console.error('Failed to load questions:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQuestions();
  }, [initialSubject]);

  const years = useMemo(() => {
    const y = [...new Set(questions.map((q) => q.year))].sort((a, b) => b - a);
    return y;
  }, [questions]);

  const units = useMemo(() => {
    const u = [...new Set(questions.map((q) => q.unit_guess).filter(Boolean))].sort();
    return u as string[];
  }, [questions]);

  const filtered = useMemo(() => {
    return questions.filter((q) => {
      if (search && !q.text.toLowerCase().includes(search.toLowerCase()) && !q.question_id.toLowerCase().includes(search.toLowerCase())) return false;
      if (filterYear && q.year !== Number(filterYear)) return false;
      if (filterUnit && q.unit_guess !== filterUnit) return false;
      if (filterReview === 'yes' && !q.needs_review) return false;
      if (filterReview === 'no' && q.needs_review) return false;
      return true;
    });
  }, [questions, search, filterYear, filterUnit, filterReview]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      {/* Header */}
      <div className={s.pageHeader}>
        <div>
          <h1>Question Corpus</h1>
          <p>
            {initialSubject ? `Questions for ${initialSubject}` : 'Browse, search, and filter the extracted question corpus across all papers.'}
          </p>
        </div>
        <span className="badge badge--info">{questions.length} total questions</span>
      </div>

      {/* Filters */}
      <div className={s.filters}>
        <div className={s.searchBar}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
          <input
            className={s.searchInput}
            placeholder="Search question text or formulas..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className={s.field}>
          <label>Year</label>
          <select className={s.select} value={filterYear} onChange={(e) => setFilterYear(e.target.value)}>
            <option value="">All years</option>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>

        <div className={s.field}>
          <label>Unit / Topic</label>
          <select className={s.select} value={filterUnit} onChange={(e) => setFilterUnit(e.target.value)}>
            <option value="">All units</option>
            {units.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>

        <div className={s.field}>
          <label>Review Status</label>
          <select className={s.select} value={filterReview} onChange={(e) => setFilterReview(e.target.value)}>
            <option value="">All</option>
            <option value="yes">Needs Review</option>
            <option value="no">Verified</option>
          </select>
        </div>
      </div>

      {/* Questions list */}
      <div className="card">
        {loading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
            <span className="spinner" style={{ marginBottom: '12px' }} />
            <div>Loading questions...</div>
          </div>
        ) : filtered.length > 0 ? (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th style={{ width: 80 }}>Q. No</th>
                  <th>Question Text</th>
                  <th style={{ width: 70 }}>Marks</th>
                  <th style={{ width: 180 }}>Unit / Topic</th>
                  <th style={{ width: 70 }}>Year</th>
                  <th style={{ width: 120 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((q) => (
                  <tr
                    key={q.question_id}
                    onClick={() => setExpandedId(expandedId === q.question_id ? null : q.question_id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Q{q.question_no}</td>
                    <td>
                      <div style={{
                        maxWidth: 550,
                        overflow: expandedId === q.question_id ? 'visible' : 'hidden',
                        textOverflow: expandedId === q.question_id ? 'unset' : 'ellipsis',
                        whiteSpace: expandedId === q.question_id ? 'normal' : 'nowrap',
                        lineHeight: 1.5,
                      }}>
                        {q.text}
                      </div>
                      {expandedId === q.question_id && q.reasoning && (
                        <div style={{ marginTop: '8px', fontSize: '13px', color: '#64748b', backgroundColor: '#f8fafc', padding: '6px 10px', borderRadius: '4px' }}>
                          <strong>Agent Reasoning:</strong> {q.reasoning}
                        </div>
                      )}
                    </td>
                    <td style={{ fontWeight: 600 }}>{q.marks}m</td>
                    <td>
                      {q.unit_guess ? (
                        <span className={s.tag} title={`Confidence: ${Math.round((q.unit_confidence || 0) * 100)}%`}>
                          {q.unit_guess}
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-tertiary)', fontSize: 'var(--text-xs)' }}>Unmapped</span>
                      )}
                    </td>
                    <td>{q.year}</td>
                    <td>
                      {q.needs_review ? (
                        <span className="badge badge--warning" title={q.review_reason || 'Review needed'}>
                          Needs Review
                        </span>
                      ) : (
                        <span className="badge badge--success">Verified</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className={s.empty}>
            <div className={s.emptyIcon}>
              <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round">
                <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
            </div>
            <h3>No questions found</h3>
            <p>
              {questions.length === 0
                ? 'Upload and process question papers first. Extracted questions will appear here.'
                : 'Try adjusting your search or filters to find what you\'re looking for.'}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
