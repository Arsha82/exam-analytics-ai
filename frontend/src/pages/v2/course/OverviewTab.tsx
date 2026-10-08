import { Link } from 'react-router-dom';
import CountUp from '../../../components/bits/CountUp';
import { useCourse } from '../courseContext';
import CoverageStrip from './CoverageStrip';
import ProbabilityBars from './ProbabilityBars';
import st from '../v2.module.css';

export default function OverviewTab() {
  const { course, snapshot, coverage, topicName } = useCourse();

  if (!snapshot || snapshot.n_papers === 0) {
    return (
      <div className={`card ${st.empty}`}>
        <h2 className={st.emptyTitle}>No papers analysed yet</h2>
        <p>
          Run <strong>Find papers</strong> to collect every {course.code} question paper from known repositories and the web, then{' '}
          <strong>Read &amp; analyse</strong> to transcribe, check and tag them. The overview fills in from real papers only.
        </p>
        {coverage && <div style={{ marginTop: 24 }}><CoverageStrip coverage={coverage} /></div>}
      </div>
    );
  }

  const bt = snapshot.backtest.summary;
  const k3 = snapshot.modules.map((m) => m.prep_sets.find((p) => p.k === 3) ?? m.prep_sets[m.prep_sets.length - 1]).filter(Boolean);
  const avgFull = k3.length ? k3.reduce((a, p) => a + p!.full_coverage, 0) / k3.length : 0;
  const avgMarks = k3.length ? k3.reduce((a, p) => a + p!.expected_part_b_marks, 0) / k3.length : 0;
  const issues = snapshot.questions_untagged;
  const mcq = course.template_id.includes('mcq');
  const first = snapshot.papers[0]?.label;
  const last = snapshot.papers[snapshot.papers.length - 1]?.label;
  const top = [...snapshot.topics].sort((a, b) => b.probability_next - a.probability_next).slice(0, 10);

  return (
    <>
      <p className={st.headline}>
        From <strong>{snapshot.n_papers} papers</strong> ({first} – {last}): preparing <strong>3 topics per module</strong> would have let you
        {mcq ? (
          <>answer about <strong>{avgMarks.toFixed(1)} of 10</strong> questions in each section.</>
        ) : (
          <>answer a full Part B question in <strong>{Math.round(avgFull * 100)}%</strong> of modules, worth about{' '}
            <strong>{avgMarks.toFixed(1)} of 14</strong> marks each.</>
        )}
        {bt.evaluated_papers > 0 && <> <Link to={`/courses/${course.code}/backtest`}>How reliable is this?</Link></>}
      </p>

      <div className={st.stats}>
        <Stat value={snapshot.n_papers} label="Distinct papers" sub={`${coverage?.found ?? 0} of ${coverage?.expected ?? 0} sessions covered`} />
        <Stat value={snapshot.questions_total} label="Questions & sub-parts" sub={issues ? `${issues} not yet tagged` : 'all tagged'} />
        <Stat value={snapshot.topics.filter((t) => t.papers_with > 0).length} label="Topics ever asked" sub={`of ${snapshot.topics.length} in the syllabus`} />
        <Stat value={snapshot.repeats.length} label="Repeat clusters" sub="asked again, same or new numbers" />
      </div>

      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>Most likely next time</div>
          <div className={st.sectionHint}>Chance each topic appears in the next paper (Beta posterior, λ = {snapshot.params.lambda} chosen by backtest; band = ±1σ). <Link to={`/courses/${course.code}/insights`}>All topics →</Link></div>
        </div>
        <div className={`card ${st.cardPad}`}>
          <ProbabilityBars topics={top} total={snapshot.n_papers} />
        </div>
      </section>

      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>Three topics per module</div>
          <div className={st.sectionHint}>The best 3-topic set for each module, chosen on past papers.</div>
        </div>
        <div className={st.prepGrid}>
          {snapshot.modules.map((m) => {
            const p = m.prep_sets.find((x) => x.k === 3) ?? m.prep_sets[m.prep_sets.length - 1];
            return (
              <div key={m.module} className={`card ${st.prepCard}`}>
                <div className="caps">Module {m.module} · {m.title}</div>
                {p ? (
                  <>
                    <div className={st.meter}>
                      <span className={`display-num ${st.meterBig}`}>{Math.round(p.full_coverage * 100)}%</span>
                      <span className={st.muted}>{mcq ? `${p.expected_part_b_marks.toFixed(1)}/10 questions of the section` : `full question · ${p.expected_part_b_marks.toFixed(1)}/14 marks · Part A ${p.part_a_marks.toFixed(1)}/6`}</span>
                    </div>
                    <div>{p.topics.map((t) => <span key={t} className={st.topicChip}>{topicName(t)}</span>)}</div>
                  </>
                ) : (
                  <span className={st.muted}>Not enough complete papers for this module.</span>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {coverage && (
        <section className={st.stack}>
          <div className={st.sectionTitle}>Sessions covered</div>
          <CoverageStrip coverage={coverage} />
        </section>
      )}
    </>
  );
}

function Stat({ value, label, sub }: { value: number; label: string; sub?: string }) {
  return (
    <div className={`card ${st.stat}`}>
      <div className={`display-num ${st.statValue}`}><CountUp to={value} duration={1.2} /></div>
      <div className={st.statLabel}>{label}</div>
      {sub && <div className={st.statSub}>{sub}</div>}
    </div>
  );
}
