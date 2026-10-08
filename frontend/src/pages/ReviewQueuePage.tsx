import { useEffect, useState, useMemo } from 'react';
import s from '../design/shared.module.css';
import { apiClient, type ReviewItem } from '../api/client';

export default function ReviewQueuePage() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState<string>('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Edit fields for override
  const [editUnit, setEditUnit] = useState('');
  const [editMarks, setEditMarks] = useState<number>(0);
  const [isEditing, setIsEditing] = useState(false);

  const fetchQueue = async () => {
    try {
      setLoading(true);
      const data = await apiClient.getReviewQueue();
      setItems(data.items);
      if (data.items.length > 0 && !selectedId) {
        setSelectedId(data.items[0].id);
      }
    } catch (err) {
      console.error('Failed to load review queue:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, []);

  const selectedItem = items.find((i) => i.id === selectedId);

  useEffect(() => {
    if (selectedItem) {
      setEditUnit(selectedItem.unit || '');
      setEditMarks(selectedItem.marks || selectedItem.marks_awarded || 0);
      setIsEditing(false);
    }
  }, [selectedId, selectedItem]);

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (filterType && item.type !== filterType) return false;
      return true;
    });
  }, [items, filterType]);

  const handleApprove = async () => {
    if (!selectedItem) return;
    try {
      await apiClient.resolveReviewItem(selectedItem.type, selectedItem.id);
      setSelectedId(null);
      await fetchQueue();
    } catch (err) {
      console.error('Failed to approve review item:', err);
    }
  };

  const handleSaveOverride = async () => {
    if (!selectedItem) return;
    try {
      const payload: any = {};
      if (editUnit) payload.unit_guess = editUnit;
      if (editMarks) {
        if (selectedItem.type === 'question') payload.marks = editMarks;
        if (selectedItem.type === 'attempt_score') payload.marks_awarded = editMarks;
      }
      await apiClient.resolveReviewItem(selectedItem.type, selectedItem.id, payload);
      setIsEditing(false);
      setSelectedId(null);
      await fetchQueue();
    } catch (err) {
      console.error('Failed to save override:', err);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      <div className={s.pageHeader}>
        <div>
          <h1>Human-in-the-Loop Review Queue</h1>
          <p>Questions or papers with low confidence scores or mark sum discrepancies flagged for manual verification.</p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span className="badge badge--warning">{items.length} Pending Actions</span>
        </div>
      </div>

      {/* Filters */}
      <div className={s.filters}>
        <div className={s.field}>
          <label>Item Type</label>
          <select className={s.select} value={filterType} onChange={(e) => setFilterType(e.target.value)}>
            <option value="">All Flagged Items</option>
            <option value="question">Questions</option>
            <option value="paper">Papers</option>
            <option value="attempt_score">Attempt Scores</option>
          </select>
        </div>
      </div>

      {/* ── Split: list + detail ── */}
      <div style={{ display: 'grid', gridTemplateColumns: selectedItem ? '1fr 1.2fr' : '1fr', gap: '20px' }}>
        {/* Item list */}
        <div className="card">
          {loading ? (
            <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
              <span className="spinner" style={{ marginBottom: '12px' }} />
              <div>Checking review queue...</div>
            </div>
          ) : filtered.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {filtered.map((item) => (
                <div
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                  style={{
                    padding: '16px',
                    borderBottom: '1px solid #e2e8f0',
                    cursor: 'pointer',
                    background: selectedId === item.id ? '#eff6ff' : 'transparent',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <span className="badge badge--warning">{item.type}</span>
                    <span style={{ fontSize: '12px', color: '#64748b' }}>
                      {item.created_at ? new Date(item.created_at).toLocaleDateString() : ''}
                    </span>
                  </div>
                  <div style={{ fontSize: '15px', fontWeight: 600, color: '#0f172a', marginBottom: '4px' }}>
                    {item.title}
                  </div>
                  <p style={{ fontSize: '13px', color: '#dc2626', margin: 0 }}>
                    {item.reason}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <div className={s.empty}>
              <div className={s.emptyIcon}>
                <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="1.5" strokeLinecap="round">
                  <polyline points="20,6 9,17 4,12" />
                </svg>
              </div>
              <h3>Review queue is completely clear</h3>
              <p>All OCR extractions, mark balances, and syllabus correlations meet target confidence thresholds.</p>
            </div>
          )}
        </div>

        {/* Detail panel */}
        {selectedItem && (
          <div className="card animate-slide-in-right" style={{ padding: '24px' }}>
            <div style={{ marginBottom: '20px' }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px' }}>
                <span className="badge badge--warning">{selectedItem.type}</span>
                <span style={{ fontSize: '12px', color: '#64748b' }}>ID: {selectedItem.id}</span>
              </div>
              <h2>{selectedItem.title}</h2>
              <div style={{ marginTop: '8px', padding: '8px 12px', backgroundColor: '#fef2f2', borderRadius: '6px', color: '#b91c1c', fontSize: '13px' }}>
                <strong>Flag Reason:</strong> {selectedItem.reason}
              </div>
            </div>

            {/* Question Text preview if available */}
            {selectedItem.text && (
              <div style={{ padding: '16px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0', marginBottom: '16px' }}>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', marginBottom: '6px', textTransform: 'uppercase' }}>
                  Extracted Content
                </div>
                <p style={{ fontSize: '14px', color: '#1e293b', lineHeight: 1.6, margin: 0 }}>
                  {selectedItem.text}
                </p>
              </div>
            )}

            {/* Edit / Override Form */}
            {isEditing ? (
              <div style={{ padding: '16px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #cbd5e1', marginBottom: '20px' }}>
                <h4 style={{ margin: '0 0 12px 0', fontSize: '14px' }}>Manual Override</h4>
                {selectedItem.type === 'question' && (
                  <div style={{ marginBottom: '12px' }}>
                    <label style={{ fontSize: '12px', fontWeight: 600, display: 'block', marginBottom: '4px' }}>Assigned Unit</label>
                    <input
                      className={s.input}
                      value={editUnit}
                      onChange={(e) => setEditUnit(e.target.value)}
                      style={{ width: '100%' }}
                    />
                  </div>
                )}
                <div style={{ marginBottom: '16px' }}>
                  <label style={{ fontSize: '12px', fontWeight: 600, display: 'block', marginBottom: '4px' }}>Marks</label>
                  <input
                    type="number"
                    className={s.input}
                    value={editMarks}
                    onChange={(e) => setEditMarks(Number(e.target.value))}
                    style={{ width: '100px' }}
                  />
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button className={s.btnPrimary} onClick={handleSaveOverride}>Save & Approve</button>
                  <button className={s.btnGhost} onClick={() => setIsEditing(false)}>Cancel</button>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: '12px', marginTop: '24px' }}>
                <button className={s.btnPrimary} onClick={handleApprove}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <polyline points="20,6 9,17 4,12" />
                  </svg>
                  Approve As-Is
                </button>
                <button className={s.btnGhost} onClick={() => setIsEditing(true)}>
                  Override & Edit
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
