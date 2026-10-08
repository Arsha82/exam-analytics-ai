import { useCourse } from '../courseContext';
import st from '../v2.module.css';

const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`);
const num = (v: number | null | undefined, d = 3) => (v == null ? '—' : v.toFixed(d));

export default function BacktestTab() {
  const { snapshot, course } = useCourse();
  const outOf = course.template_id.includes('mcq') ? 10 : 14;
  if (!snapshot) {
    return <div className={`card ${st.empty}`}><h2 className={st.emptyTitle}>No backtest yet</h2><p>It runs with the insights.</p></div>;
  }
  const { summary, rows } = snapshot.backtest;
  const ps = summary.prep_set;
  return (
    <>
      <p className={st.headline}>{summary.verdict}</p>

      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>How it is scored</div>
          <div className={st.sectionHint}>
            Papers in date order. For every paper after the first {summary.warmup}, the model only sees the papers before it, then is scored on it.
            Lower Brier is better; prep-set columns use {summary.k} topics per module.
          </div>
        </div>
        <div className={st.stats}>
          <Metric label="Brier — model" value={num(summary.brier.model)} hint={`frequency ${num(summary.brier.frequency)} · uniform ${num(summary.brier.uniform)}`} />
          <Metric label="Recall@k — model" value={pct(summary.recall_at_k.model)} hint={`frequency ${pct(summary.recall_at_k.frequency)}`} />
          <Metric label={`Prep set (${summary.k}) full question`} value={pct(ps.model_full)} hint={`frequency top-${summary.k} ${pct(ps.freq_full)} · random ${pct(ps.random_full)}`} />
          <Metric label={outOf === 10 ? 'Prep set marks per section' : 'Prep set Part B marks'} value={ps.model_marks == null ? '—' : `${ps.model_marks.toFixed(1)}/${outOf}`} hint={`frequency ${ps.freq_marks?.toFixed(1) ?? '—'} · random ${ps.random_marks?.toFixed(1) ?? '—'}`} />
        </div>
      </section>

      <section className={st.stack}>
        <div className={st.sectionTitle}>Paper by paper</div>
        <div className={`card ${st.tableCard}`}>
          <table className={st.table}>
            <thead>
              <tr><th>Predicted paper</th><th>Trained on</th><th>Topics present</th><th>Brier model / freq</th><th>Recall@k</th><th>Prep set full / freq / random</th><th>Part B marks</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.paper_id}>
                  <td>{r.label}</td>
                  <td className={st.num}>{r.trained_on}</td>
                  <td className={st.num}>{r.topics_present}</td>
                  <td className={st.num}>{num(r.brier.model)} / {num(r.brier.frequency)}</td>
                  <td className={st.num}>{pct(r.recall_at_k.model)}</td>
                  <td className={st.num}>{pct(r.prep_set.model_full)} / {pct(r.prep_set.freq_full)} / {pct(r.prep_set.random_full)}</td>
                  <td className={st.num}>{r.prep_set.model_marks == null ? '—' : r.prep_set.model_marks.toFixed(1)}</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={7} className={st.muted}>Needs more than {summary.warmup} papers.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className={`card ${st.stat}`}>
      <div className={`display-num ${st.statValue}`}>{value}</div>
      <div className={st.statLabel}>{label}</div>
      <div className={st.statSub}>{hint}</div>
    </div>
  );
}
