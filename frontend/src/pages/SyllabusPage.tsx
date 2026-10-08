import { useEffect, useState } from 'react';
import s from '../design/shared.module.css';
import { apiClient } from '../api/client';

interface SyllabusUnit {
  unit: string;
  topics: {
    topic: string;
    sub_topics: { sub_topic: string; node_id: string; description: string; embedded: boolean }[];
    node_id: string;
    description: string;
    embedded: boolean;
  }[];
}

const SAMPLE_SYLLABI: Record<string, any[]> = {
  'Mathematics': [
    { unit: 'Unit 1: Differential Calculus', topic: 'Rolle’s & Mean Value Theorems', description: 'Rolle’s theorem, Cauchy’s mean value theorem, Taylor and Maclaurin series expansion.' },
    { unit: 'Unit 1: Differential Calculus', topic: 'Partial Differentiation', description: 'Euler’s theorem on homogeneous functions, Jacobians, maxima and minima of several variables.' },
    { unit: 'Unit 2: Linear Algebra', topic: 'Matrices & Rank', description: 'Rank of matrix by echelon form, system of linear equations, Gauss elimination.' },
    { unit: 'Unit 2: Linear Algebra', topic: 'Eigenvalues & Vectors', description: 'Characteristic equations, Cayley-Hamilton theorem, diagonalization of symmetric matrices.' },
    { unit: 'Unit 3: Vector Calculus', topic: 'Vector Integration', description: 'Line integrals, surface integrals, volume integrals, Green’s, Gauss divergence, and Stokes’ theorems.' },
  ],
  'DBMS': [
    { unit: 'Unit 1: ER Model & Relational Model', topic: 'ER Diagrams', description: 'Entities, relationships, attributes, cardinalities, ER to relational mapping.' },
    { unit: 'Unit 2: SQL & Relational Algebra', topic: 'Relational Algebra', description: 'Selection, projection, joins, set operations, division.' },
    { unit: 'Unit 3: Normalization', topic: 'Functional Dependencies', description: '1NF, 2NF, 3NF, BCNF, lossless join decomposition, dependency preservation.' },
    { unit: 'Unit 4: Transaction Processing', topic: 'ACID Properties & Concurrency', description: 'Serializability, two-phase locking (2PL), deadlock prevention and detection.' },
  ]
};

export default function SyllabusPage() {
  const [units, setUnits] = useState<SyllabusUnit[]>([]);
  const [totalNodes, setTotalNodes] = useState(0);
  const [subject, setSubject] = useState('Mathematics');
  const [loading, setLoading] = useState(true);
  const [showImportModal, setShowImportModal] = useState(false);
  const [importJsonText, setImportJsonText] = useState('');
  const [importSubject, setImportSubject] = useState('Mathematics');
  const [expandedUnit, setExpandedUnit] = useState<string | null>(null);

  const fetchSyllabus = async () => {
    try {
      setLoading(true);
      const data = await apiClient.getSyllabus(subject);
      setUnits(data.units || []);
      setTotalNodes(data.total_nodes || 0);
      if (data.units && data.units.length > 0 && !expandedUnit) {
        setExpandedUnit(data.units[0].unit);
      }
    } catch (err) {
      console.error('Failed to load syllabus:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSyllabus();
  }, [subject]);

  const handleQuickLoad = async (subName: string) => {
    const nodes = SAMPLE_SYLLABI[subName];
    if (!nodes) return;
    try {
      setLoading(true);
      await apiClient.importSyllabus(subName, nodes);
      setSubject(subName);
      await fetchSyllabus();
      setShowImportModal(false);
    } catch (err) {
      console.error('Failed to quick load syllabus:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleCustomImport = async () => {
    try {
      const parsed = JSON.parse(importJsonText);
      const nodes = Array.isArray(parsed) ? parsed : (parsed.nodes || []);
      setLoading(true);
      await apiClient.importSyllabus(importSubject, nodes);
      setSubject(importSubject);
      await fetchSyllabus();
      setShowImportModal(false);
    } catch (err) {
      alert('Invalid JSON: Please ensure format is an array of { unit, topic, description }');
    } finally {
      setLoading(false);
    }
  };

  const handleReembed = async () => {
    try {
      setLoading(true);
      await apiClient.reembedSyllabus(subject);
      alert('Vector embeddings successfully generated and synchronized in ChromaDB.');
      await fetchSyllabus();
    } catch (err) {
      alert('Re-embedding failed: ' + err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      <div className={s.pageHeader}>
        <div>
          <h1>Curriculum & Syllabus Index</h1>
          <p>Syllabus nodes are embedded into ChromaDB via nomic-embed-text for question correlation and topic weighting.</p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
          {totalNodes > 0 && (
            <span className="badge badge--success">{totalNodes} nodes indexed</span>
          )}
          <button className={s.btnGhost} onClick={handleReembed} title="Recompute nomic-embed-text vectors">
            Sync Vectors
          </button>
          <button className={s.btnPrimary} onClick={() => setShowImportModal(true)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="17,8 12,3 7,8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            Import Syllabus
          </button>
        </div>
      </div>

      {/* Subject selector tabs */}
      <div style={{ display: 'flex', gap: '8px' }}>
        {['Mathematics', 'DBMS'].map((sub) => (
          <button
            key={sub}
            onClick={() => setSubject(sub)}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              border: subject === sub ? '2px solid #2563eb' : '1px solid #cbd5e1',
              backgroundColor: subject === sub ? '#eff6ff' : '#ffffff',
              color: subject === sub ? '#1e40af' : '#475569',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {sub}
          </button>
        ))}
      </div>

      {/* Units Tree */}
      {loading ? (
        <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
          <span className="spinner" style={{ marginBottom: '12px' }} />
          <div>Synchronizing curriculum index...</div>
        </div>
      ) : units.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {units.map((unit) => (
            <div key={unit.unit} className="card" style={{ overflow: 'hidden' }}>
              {/* Unit header */}
              <button
                onClick={() => setExpandedUnit(expandedUnit === unit.unit ? null : unit.unit)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
                  width: '100%', padding: 'var(--space-4) var(--space-5)',
                  textAlign: 'left', cursor: 'pointer', background: 'none', border: 'none',
                  fontSize: 'var(--text-base)', fontWeight: 600,
                  color: 'var(--text-primary)',
                }}
              >
                <svg
                  width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                  style={{ transform: expandedUnit === unit.unit ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 0.2s' }}
                >
                  <polyline points="9,18 15,12 9,6" />
                </svg>
                <span style={{ flex: 1 }}>{unit.unit}</span>
                <span className={s.tag}>{unit.topics.length} topics</span>
              </button>

              {/* Topics */}
              {expandedUnit === unit.unit && (
                <div style={{ borderTop: '1px solid var(--surface-border)', padding: '0 var(--space-5) var(--space-4)' }}>
                  {unit.topics.map((topic) => (
                    <div key={topic.node_id} style={{ marginTop: 'var(--space-3)' }}>
                      <div
                        style={{
                          display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
                          padding: '8px 12px',
                          borderRadius: '6px',
                          backgroundColor: '#f8fafc',
                        }}
                      >
                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#22c55e', flexShrink: 0 }} />
                        <span style={{ flex: 1, fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>{topic.topic}</span>
                        <span style={{ fontSize: '13px', color: '#64748b', maxWidth: 450 }}>{topic.description}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="card">
          <div className={s.empty}>
            <div className={s.emptyIcon}>
              <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round">
                <path d="M4 19.5v-15A2.5 2.5 0 016.5 2H20v20H6.5A2.5 2.5 0 014 19.5z" />
                <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
              </svg>
            </div>
            <h3>No syllabus imported for {subject}</h3>
            <p>Load standard curriculum nodes or import custom JSON to enable semantic question mapping.</p>
            <div style={{ marginTop: '16px', display: 'flex', gap: '12px' }}>
              <button className={s.btnPrimary} onClick={() => handleQuickLoad(subject)}>
                Load Standard {subject} Syllabus
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Import Modal */}
      {showImportModal && (
        <div
          style={{
            position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          }}
        >
          <div
            className="card"
            style={{ width: '550px', maxWidth: '90vw', padding: '24px', backgroundColor: '#fff' }}
          >
            <h2>Import Syllabus</h2>
            <p style={{ fontSize: '14px', color: '#64748b', marginBottom: '16px' }}>
              Quick-load standard syllabus or paste a JSON array of syllabus nodes.
            </p>

            <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
              <button className={s.btnGhost} onClick={() => handleQuickLoad('Mathematics')}>
                Load Mathematics Preset
              </button>
              <button className={s.btnGhost} onClick={() => handleQuickLoad('DBMS')}>
                Load DBMS Preset
              </button>
            </div>

            <div style={{ marginBottom: '12px' }}>
              <label style={{ fontSize: '13px', fontWeight: 600, display: 'block', marginBottom: '4px' }}>Subject</label>
              <input
                type="text"
                className={s.input}
                value={importSubject}
                onChange={(e) => setImportSubject(e.target.value)}
                style={{ width: '100%' }}
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ fontSize: '13px', fontWeight: 600, display: 'block', marginBottom: '4px' }}>JSON Nodes Array</label>
              <textarea
                rows={6}
                className={s.input}
                value={importJsonText}
                onChange={(e) => setImportJsonText(e.target.value)}
                placeholder='[{"unit": "Unit 1", "topic": "Calculus", "description": "Limits and derivatives"}]'
                style={{ width: '100%', fontFamily: 'monospace', fontSize: '12px' }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button className={s.btnGhost} onClick={() => setShowImportModal(false)}>Cancel</button>
              <button className={s.btnPrimary} onClick={handleCustomImport} disabled={!importJsonText.trim()}>
                Import & Embed
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
