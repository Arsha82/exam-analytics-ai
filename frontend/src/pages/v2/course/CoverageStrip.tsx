import type { Coverage } from '../../../api/v2';
import st from '../v2.module.css';

/** Expected exam sessions (regular / supplementary) vs the papers actually found. */
export default function CoverageStrip({ coverage }: { coverage: Coverage }) {
  return (
    <div className={st.stack}>
      <div className={st.coverage}>
        {coverage.windows.map((w) => (
          <div key={w.label} className={w.papers.length ? st.covFound : st.covCell} title={w.papers.map((p) => `${p.label} · QP ${p.qp_code ?? '?'}`).join('\n')}>
            <div className={st.covKind}>{w.kind === 'regular' ? 'Regular' : 'Supplementary'}</div>
            <div className={st.covLabel}>{w.kind === 'regular' ? `Nov/Dec ${w.year}` : `May/Jun ${w.year}`}</div>
            <div className={st.covPapers}>
              {w.papers.length ? w.papers.map((p) => p.label).join(', ') : 'not found'}
            </div>
          </div>
        ))}
      </div>
      {coverage.other.length > 0 && (
        <div className={st.muted}>Outside the usual windows: {coverage.other.map((p) => p.label).join(', ')}</div>
      )}
    </div>
  );
}
