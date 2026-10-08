import { useMemo, useState } from 'react';
import type { ModuleInsight, Snapshot } from '../../../api/v2';
import MathText from '../../../components/v2/MathText';
import { useCourse } from '../courseContext';
import ProbabilityBars from './ProbabilityBars';
import st from '../v2.module.css';

export default function InsightsTab() {
  const { snapshot, course } = useCourse();
  if (!snapshot || snapshot.n_papers === 0) {
    return (
      <div className={`card ${st.empty}`}>
        <h2 className={st.emptyTitle}>Insights appear after papers are analysed</h2>
        <p>Every number here is computed from the questions table, so it stays reproducible and updates when you fix a transcription.</p>
      </div>
    );
  }
  return (
    <>
      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>Where the marks went</div>
          <div className={st.sectionHint}>Marks per topic in each paper (multi-topic questions split their marks). Darker = more marks. Rows grouped by module.</div>
        </div>
        <div className={`card ${st.cardPad}`}><Heatmap snapshot={snapshot} /></div>
      </section>

      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>Minimum prep sets</div>
          <div className={st.sectionHint}>
            For each module, the smallest set of topics that would have let you answer one full either/or question in past papers.
            Chosen by exhaustive search over all topic combinations.
          </div>
        </div>
        <div className={st.prepGrid}>
          {snapshot.modules.map((m) => <PrepExplorer key={m.module} m={m} />)}
        </div>
      </section>

      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>Chance of appearing next time</div>
          <div className={st.sectionHint}>Beta posterior, recency weight λ = {snapshot.params.lambda} (chosen by backtest; 1 = plain frequency); numbers on the right are papers-with / papers.</div>
        </div>
        <div className={st.moduleBars}>
          {course.modules.map((m) => (
            <div key={m.no} className={`card ${st.cardPad}`}>
              <div className="caps" style={{ marginBottom: 8 }}>Module {m.no} · {m.title}</div>
              <ProbabilityBars total={snapshot.n_papers}
                topics={snapshot.topics.filter((t) => t.module === m.no).sort((a, b) => b.probability_next - a.probability_next)} />
            </div>
          ))}
        </div>
      </section>

      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>What kind of questions</div>
          <div className={st.sectionHint}>Theory (define/state/explain) · derivation (derive/prove) · problem (solve/evaluate/find), per module and part.</div>
        </div>
        <div className={`card ${st.tableCard}`}><KindsTable modules={snapshot.modules} /></div>
      </section>

      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>Asked again ({snapshot.repeats.length})</div>
          <div className={st.sectionHint}>Same question (repeat) or same method with new numbers (template), across different papers.</div>
        </div>
        <div className={st.stack}>
          {snapshot.repeats.slice(0, 30).map((c, i) => (
            <div key={i} className={`card ${st.cardPad}`}>
              <div className={st.row} style={{ marginBottom: 8 }}>
                <span className={c.relation === 'repeat' ? 'badge badge--danger' : 'badge badge--info'}>{c.relation}</span>
                <span className="caps">Module {c.module} · asked {c.times}×</span>
              </div>
              {c.questions.map((q) => (
                <div key={q.question_id} className={st.repeatLine}>
                  <span className={st.repeatWhere}>{q.paper} · Q{q.number}{q.sub ?? ''}</span>
                  <MathText text={q.text} />
                </div>
              ))}
            </div>
          ))}
          {snapshot.repeats.length === 0 && <div className={st.muted}>No repeats detected yet.</div>}
        </div>
      </section>
    </>
  );
}

function Heatmap({ snapshot }: { snapshot: Snapshot }) {
  const { course } = useCourse();
  const cells = useMemo(() => {
    const m = new Map<string, (typeof snapshot.heatmap)[number]>();
    for (const c of snapshot.heatmap) m.set(`${c.topic_id}|${c.paper_id}`, c);
    return m;
  }, [snapshot]);
  const max = Math.max(1, ...snapshot.heatmap.map((c) => c.marks));
  const stats = new Map(snapshot.topics.map((t) => [t.topic_id, t]));
  const level = (marks: number) => (marks <= 0 ? 0 : Math.min(5, Math.ceil((marks / max) * 5)));

  return (
    <div className={st.heatWrap}>
      <table className={st.heat}>
        <thead>
          <tr>
            <th />
            {snapshot.papers.map((p) => <th key={p.paper_id}><span className={st.heatColHead}>{p.label}</span></th>)}
            <th className={st.heatRate}>seen</th>
          </tr>
        </thead>
        <tbody>
          {course.modules.map((m) => (
            <Fragment key={m.no}>
              <tr className={st.heatModule}><td colSpan={snapshot.papers.length + 2}>Module {m.no} · {m.title}</td></tr>
              {m.topics.map((t) => {
                const stat = stats.get(t.id);
                return (
                  <tr key={t.id}>
                    <td className={st.heatTopic} title={t.name}>{t.name}</td>
                    {snapshot.papers.map((p) => {
                      const c = cells.get(`${t.id}|${p.paper_id}`);
                      const lv = c ? level(c.marks) : 0;
                      return (
                        <td key={p.paper_id} className={c ? st.heatCell : st.heatEmpty}
                          style={{ background: `var(--scale-${lv})`, color: lv >= 4 ? 'var(--ink-inverse)' : undefined }}
                          title={c ? `${t.name}\n${p.label}: ${c.marks} marks · Q${c.questions.join(', Q')}` : `${t.name}\n${p.label}: not asked`}>
                          {c ? Math.round(c.marks) : ''}
                        </td>
                      );
                    })}
                    <td className={st.heatRate}>{stat ? `${stat.papers_with}/${snapshot.n_papers}` : ''}</td>
                  </tr>
                );
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PrepExplorer({ m }: { m: ModuleInsight }) {
  const { topicName, course } = useCourse();
  const mcq = course.template_id.includes('mcq');
  const [k, setK] = useState(Math.min(3, m.prep_sets.length));
  const p = m.prep_sets.find((x) => x.k === k);
  return (
    <div className={`card ${st.prepCard}`}>
      <div className={st.row}>
        <span className="caps">Module {m.module}</span>
        <span className={st.spacer} />
        <div className={st.kButtons} role="group" aria-label="Number of topics">
          {m.prep_sets.map((x) => (
            <button key={x.k} className={x.k === k ? st.kBtnActive : st.kBtn} onClick={() => setK(x.k)}>{x.k}</button>
          ))}
        </div>
      </div>
      <div className={st.prepTitle}>{m.title}</div>
      {p ? (
        <>
          <div className={st.meter}>
            <span className={`display-num ${st.meterBig}`}>{Math.round(p.full_coverage * 100)}%</span>
            <span className={st.muted}>of {m.papers_evaluated} papers {mcq ? 'had every question of this section covered' : 'had a fully answerable choice'}</span>
          </div>
          <div className={st.prepNums}>
            {mcq ? (
              <span><strong>{p.expected_part_b_marks.toFixed(1)}</strong>/10 marks of this section on average</span>
            ) : (
              <>
                <span><strong>{p.expected_part_b_marks.toFixed(1)}</strong>/14 Part B marks on average</span>
                <span><strong>{p.part_a_marks.toFixed(1)}</strong>/6 Part A marks</span>
              </>
            )}
          </div>
          <div>{p.topics.map((t) => <span key={t} className={st.topicChip}>{topicName(t)}</span>)}</div>
        </>
      ) : (
        <span className={st.muted}>Not enough complete papers.</span>
      )}
    </div>
  );
}

function KindsTable({ modules }: { modules: ModuleInsight[] }) {
  const kinds = ['theory', 'derivation', 'problem'];
  return (
    <table className={st.table}>
      <thead>
        <tr><th>Module</th>{kinds.map((k) => <th key={`a${k}`}>A · {k}</th>)}{kinds.map((k) => <th key={`b${k}`}>B · {k}</th>)}</tr>
      </thead>
      <tbody>
        {modules.map((m) => (
          <tr key={m.module}>
            <td>{m.module} · {m.title}</td>
            {kinds.map((k) => <td key={`a${k}`} className={st.num}>{m.kinds.A[k] ?? 0}</td>)}
            {kinds.map((k) => <td key={`b${k}`} className={st.num}>{m.kinds.B[k] ?? 0}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

import { Fragment } from 'react';
