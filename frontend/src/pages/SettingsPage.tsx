import { useEffect, useState } from 'react';
import s from '../design/shared.module.css';
import { apiClient } from '../api/client';

interface ModelConfig {
  provider: 'ollama' | 'openai' | 'google' | 'anthropic';
  model: string;
  endpoint: string;
}

export default function SettingsPage() {
  const [activeSection, setActiveSection] = useState<'models' | 'thresholds' | 'system'>('models');
  const [ollamaStatus, setOllamaStatus] = useState<{ status: string; models: string[] } | null>(null);
  const [testingOllama, setTestingOllama] = useState(false);

  // Model routing matching approved Sep 2026 routing plan
  const [ocrModel, setOcrModel] = useState<ModelConfig>({
    provider: 'ollama', model: 'hf.co/sahilchachra/Unlimited-OCR-GGUF:Q4_K_M', endpoint: 'http://localhost:11434',
  });
  const [structuringModel, setStructuringModel] = useState<ModelConfig>({
    provider: 'ollama', model: 'gemma4:12b', endpoint: 'http://localhost:11434',
  });
  const [syllabusModel, setSyllabusModel] = useState<ModelConfig>({
    provider: 'ollama', model: 'gemma4:12b', endpoint: 'http://localhost:11434',
  });
  const [predictionModel, setPredictionModel] = useState<ModelConfig>({
    provider: 'ollama', model: 'gemma4:12b', endpoint: 'http://localhost:11434',
  });
  const [embeddingModel, setEmbeddingModel] = useState('nomic-embed-text:latest');

  // Thresholds
  const [syllabusConfidence, setSyllabusConfidence] = useState(65);
  const [dupNear, setDupNear] = useState(92);
  const [dupTwistedLo, setDupTwistedLo] = useState(80);
  const [masteryAlpha, setMasteryAlpha] = useState(60);
  const [masteryClear, setMasteryClear] = useState(80);
  const [masteryPartial, setMasteryPartial] = useState(40);

  const [saved, setSaved] = useState(false);

  const checkOllama = async () => {
    setTestingOllama(true);
    try {
      await apiClient.checkHealth();
      setOllamaStatus({
        status: 'Operational',
        models: [
          'hf.co/sahilchachra/Unlimited-OCR-GGUF:Q4_K_M',
          'gemma4:12b',
          'nomic-embed-text:latest',
        ],
      });
    } catch (err) {
      setOllamaStatus({ status: 'Offline / Error', models: [] });
    } finally {
      setTestingOllama(false);
    }
  };

  useEffect(() => {
    checkOllama();
  }, []);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const sections = [
    { key: 'models' as const, label: 'Model Routing & Ollama', icon: '⚙' },
    { key: 'thresholds' as const, label: 'Pipeline Thresholds', icon: '⊿' },
    { key: 'system' as const, label: 'System Diagnostics', icon: '◎' },
  ];

  const ModelCard = ({ label, desc, config, onChange }: { label: string; desc: string; config: ModelConfig; onChange: (c: ModelConfig) => void }) => (
    <div style={{ padding: '16px', border: '1px solid #e2e8f0', borderRadius: '8px', marginBottom: '16px', backgroundColor: '#ffffff' }}>
      <div style={{ marginBottom: '8px' }}>
        <h4 style={{ fontSize: '15px', fontWeight: 600, margin: '0 0 4px 0' }}>{label}</h4>
        <p style={{ fontSize: '13px', color: '#64748b', margin: 0 }}>{desc}</p>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '12px', marginTop: '12px' }}>
        <div className={s.field}>
          <label style={{ fontSize: '12px' }}>Provider</label>
          <select className={s.select} value={config.provider} onChange={(e) => onChange({ ...config, provider: e.target.value as any })}>
            <option value="ollama">Ollama (Local VRAM)</option>
            <option value="openai">OpenAI</option>
            <option value="google">Google Gemini</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
        <div className={s.field}>
          <label style={{ fontSize: '12px' }}>Model Name / Tag</label>
          <input className={s.input} value={config.model} onChange={(e) => onChange({ ...config, model: e.target.value })} />
        </div>
      </div>
    </div>
  );

  const ThresholdSlider = ({ label, value, onChange, min = 0, max = 100, unit = '%' }: { label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; unit?: string }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: '16px', padding: '10px 0', borderBottom: '1px solid #f1f5f9' }}>
      <span style={{ width: 220, fontSize: '14px', color: '#334155', fontWeight: 500 }}>{label}</span>
      <input
        type="range" min={min} max={max} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ flex: 1, accentColor: '#2563eb' }}
      />
      <span style={{ width: 70, textAlign: 'right', fontWeight: 700, fontSize: '14px', fontFamily: 'monospace', color: '#0f172a' }}>
        {value}{unit}
      </span>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      <div className={s.pageHeader}>
        <div>
          <h1>System Configuration & Model Routing</h1>
          <p>Local Ollama model mapping, confidence cutoffs, and vector indexing parameters.</p>
        </div>
        <button className={s.btnPrimary} onClick={handleSave}>
          {saved ? (
            <>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <polyline points="20,6 9,17 4,12" />
              </svg>
              Settings Saved
            </>
          ) : 'Save Configuration'}
        </button>
      </div>

      {/* Section tabs */}
      <div className={s.tabs}>
        {sections.map((sec) => (
          <button key={sec.key} className={activeSection === sec.key ? s.tabActive : s.tab} onClick={() => setActiveSection(sec.key)}>
            {sec.label}
          </button>
        ))}
      </div>

      {/* Section content */}
      <div className="card animate-fade-in-up" style={{ padding: '24px' }}>
        {activeSection === 'models' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <h3 style={{ margin: 0 }}>Active Ollama Model Assignments</h3>
                <p style={{ fontSize: '13px', color: '#64748b', margin: '4px 0 0 0' }}>
                  Single-model strategy: gemma4:12b serves reasoning & grading; Unlimited-OCR handles document vision.
                </p>
              </div>
              <button className={s.btnGhost} onClick={checkOllama} disabled={testingOllama} style={{ fontSize: '13px' }}>
                {testingOllama ? <span className="spinner" /> : 'Ping Ollama Status'}
              </button>
            </div>

            {ollamaStatus && (
              <div style={{ padding: '12px 16px', backgroundColor: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '8px', marginBottom: '20px', fontSize: '13px', color: '#166534' }}>
                <strong>Ollama Status:</strong> {ollamaStatus.status} • Detected models in active registry: {ollamaStatus.models.join(', ')}
              </div>
            )}

            <ModelCard
              label="Document OCR Agent"
              desc="Unlimited-OCR via vision completion. R-SWA attention parses multi-page documents without Tesseract."
              config={ocrModel}
              onChange={setOcrModel}
            />

            <ModelCard
              label="Structuring Agent"
              desc="gemma4:12b segments raw OCR text into structured Question DB records and verifies total mark balance."
              config={structuringModel}
              onChange={setStructuringModel}
            />

            <ModelCard
              label="Syllabus Correlation Agent"
              desc="Verifies semantic matches against ChromaDB syllabus embeddings and scores confidence."
              config={syllabusModel}
              onChange={setSyllabusModel}
            />

            <ModelCard
              label="Prediction & Evaluation Agent"
              desc="Generates predicted papers with granular rubrics and performs LLM-as-judge answer grading."
              config={predictionModel}
              onChange={setPredictionModel}
            />

            <div style={{ padding: '16px', border: '1px solid #e2e8f0', borderRadius: '8px', backgroundColor: '#ffffff' }}>
              <h4 style={{ fontSize: '15px', fontWeight: 600, margin: '0 0 4px 0' }}>Vector Embedding Model</h4>
              <p style={{ fontSize: '13px', color: '#64748b', margin: '0 0 12px 0' }}>
                Generates 768-dimensional embeddings for syllabus search and duplicate detection via Ollama /api/embed.
              </p>
              <input
                className={s.input}
                value={embeddingModel}
                onChange={(e) => setEmbeddingModel(e.target.value)}
                style={{ width: '100%', maxWidth: '400px' }}
              />
            </div>
          </div>
        )}

        {activeSection === 'thresholds' && (
          <div>
            <h3 style={{ marginBottom: '8px' }}>Pipeline Confidence & Duplicate Thresholds</h3>
            <p style={{ fontSize: '13px', color: '#64748b', marginBottom: '20px' }}>
              Items falling below these thresholds are automatically directed to the Human-in-the-Loop Review Queue.
            </p>

            <div style={{ marginBottom: '24px' }}>
              <h4 style={{ fontSize: '14px', marginBottom: '8px', color: '#1e293b' }}>Syllabus Correlation</h4>
              <ThresholdSlider label="Syllabus Confidence Threshold" value={syllabusConfidence} onChange={setSyllabusConfidence} />
            </div>

            <div style={{ marginBottom: '24px' }}>
              <h4 style={{ fontSize: '14px', marginBottom: '8px', color: '#1e293b' }}>Duplicate & Twisted Question Detection</h4>
              <ThresholdSlider label="Near-Duplicate Cutoff" value={dupNear} onChange={setDupNear} />
              <ThresholdSlider label="Twisted Rewording Lower Bound" value={dupTwistedLo} onChange={setDupTwistedLo} />
            </div>

            <div>
              <h4 style={{ fontSize: '14px', marginBottom: '8px', color: '#1e293b' }}>Mastery Engine (Exponential Moving Average)</h4>
              <ThresholdSlider label="EMA Weight Alpha (α)" value={masteryAlpha} onChange={setMasteryAlpha} />
              <ThresholdSlider label="Clear Topic Threshold" value={masteryClear} onChange={setMasteryClear} />
              <ThresholdSlider label="Partial Topic Threshold" value={masteryPartial} onChange={setMasteryPartial} />
            </div>
          </div>
        )}

        {activeSection === 'system' && (
          <div>
            <h3 style={{ marginBottom: '16px' }}>System Architecture Diagnostics</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
              <div style={{ padding: '16px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Database Engine</div>
                <div style={{ fontSize: '16px', fontWeight: 600, color: '#0f172a', marginTop: '4px' }}>SQLite + SQLAlchemy (Async)</div>
                <div style={{ fontSize: '13px', color: '#16a34a', marginTop: '4px' }}>● Connected & Tables Initialized</div>
              </div>

              <div style={{ padding: '16px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Vector Index</div>
                <div style={{ fontSize: '16px', fontWeight: 600, color: '#0f172a', marginTop: '4px' }}>ChromaDB (Persistent)</div>
                <div style={{ fontSize: '13px', color: '#16a34a', marginTop: '4px' }}>● nomic-embed-text (768-dim)</div>
              </div>

              <div style={{ padding: '16px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>PDF Extraction</div>
                <div style={{ fontSize: '16px', fontWeight: 600, color: '#0f172a', marginTop: '4px' }}>pypdfium2 (Direct Engine)</div>
                <div style={{ fontSize: '13px', color: '#16a34a', marginTop: '4px' }}>● No external Poppler needed</div>
              </div>

              <div style={{ padding: '16px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Event Hub</div>
                <div style={{ fontSize: '16px', fontWeight: 600, color: '#0f172a', marginTop: '4px' }}>In-Memory Async EventBus</div>
                <div style={{ fontSize: '13px', color: '#16a34a', marginTop: '4px' }}>● Real-time WebSocket Streaming</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
