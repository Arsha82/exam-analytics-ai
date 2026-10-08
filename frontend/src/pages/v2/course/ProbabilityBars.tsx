import type { TopicStat } from '../../../api/v2';
import st from '../v2.module.css';

/** Posterior mean with a ±1σ band; the text shows papers-with / papers so N is never hidden. */
export default function ProbabilityBars({ topics, total }: { topics: TopicStat[]; total?: number }) {
  return (
    <div role="list">
      {topics.map((t) => {
        const lo = Math.max(0, t.probability_next - t.probability_sd);
        const hi = Math.min(1, t.probability_next + t.probability_sd);
        return (
          <div key={t.topic_id} className={st.barRow} role="listitem"
            title={`Seen in ${t.papers_with} paper(s)${t.last_seen ? `, last ${t.last_seen}` : ''}. Part A ${Math.round(t.part_a_rate * 100)}%, Part B ${Math.round(t.part_b_rate * 100)}%.`}>
            <span className={st.barName}><span className={st.barModule}>M{t.module}</span>{t.name}</span>
            <span className={st.barTrack}>
              <span className={st.barBand} style={{ left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }} />
              <span className={st.barFill} style={{ width: `${t.probability_next * 100}%` }} />
            </span>
            <span className={st.barValue}>
              {Math.round(t.probability_next * 100)}%
              <span className={st.barN}>{t.papers_with}/{total ?? '—'}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
