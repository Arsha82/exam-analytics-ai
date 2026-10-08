import { useEffect, useMemo, useState } from 'react';
import { studyApi, type BankRow, type MockPaper } from '../../../api/v2';
import MathText from '../../../components/v2/MathText';
import Options from '../../../components/v2/Options';
import { useCourse } from '../courseContext';
import st from '../v2.module.css';
import s from '../../../design/shared.module.css';

const FOCUS = [
  { key: 'likely', label: 'Most likely', hint: 'weighted by how often each topic is asked' },
  { key: 'balanced', label: 'Balanced', hint: 'every topic equally' },
  { key: 'fresh', label: 'Fresh', hint: 'topics you have not practised yet' },
];

export default function PracticeTab() {
  const { course, topicName } = useCourse();
  const [mocks, setMocks] = useState<MockPaper[]>([]);
  const [open, setOpen] = useState<MockPaper | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bank, setBank] = useState<BankRow[] | null>(null);
  const [module, setModule] = useState<number | ''>('');
  const [topic, setTopic] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    studyApi.mocks(course.code).then(setMocks).catch(() => setMocks([]));
  }, [course.code]);

  useEffect(() => {
    const t = setTimeout(() => {
      studyApi.questions(course.code, { module: module || undefined, topic: topic || undefined, q: query || undefined })
        .then((r) => setBank(r.questions)).catch(() => setBank([]));
    }, 200);
    return () => clearTimeout(t);
  }, [course.code, module, topic, query]);

  const make = async (focus: string) => {
    setBusy(true);
    setError(null);
    try {
      const mp = await studyApi.createMock(course.code, focus);
      setOpen(mp);
      setMocks(await studyApi.mocks(course.code));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Could not build a paper');
    } finally {
      setBusy(false);
    }
  };

  const topicsOfModule = useMemo(() => course.modules.find((m) => m.no === module)?.topics ?? [], [course, module]);

  return (
    <>
      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>Practice papers</div>
          <div className={st.sectionHint}>
            {course.template_id.includes('mcq')
              ? 'Built from real past questions — ten per section, each with all four options —'
              : 'Built from real past questions — two Part A questions and two whole either/or Part B questions per module, from different papers —'}
            and checked with the same exam-format validator as the real papers.
          </div>
        </div>
        <div className={st.row}>
          {FOCUS.map((f) => (
            <button key={f.key} className={f.key === 'likely' ? s.btnPrimary : s.btnGhost} disabled={busy} title={f.hint} onClick={() => make(f.key)}>
              {busy ? 'Building…' : `New paper · ${f.label}`}
            </button>
          ))}
        </div>
        {error && <div className={st.flagNote}>{error}</div>}
        {mocks.length > 0 && (
          <div className={st.row}>
            {mocks.slice(0, 8).map((m) => (
              <button key={m.id} className={open?.id === m.id ? st.kBtnActive : st.kBtn}
                onClick={async () => setOpen(await studyApi.mock(m.id))}>{m.title}</button>
            ))}
          </div>
        )}
        {open?.items && <MockView paper={open} />}
      </section>

      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>Question bank</div>
          <div className={st.sectionHint}>Every transcribed question, filterable by module and topic. Flagged transcriptions are marked.</div>
        </div>
        <div className={st.row}>
          <select className={s.select} value={module} onChange={(e) => { setModule(e.target.value ? Number(e.target.value) : ''); setTopic(''); }}>
            <option value="">All modules</option>
            {course.modules.map((m) => <option key={m.no} value={m.no}>Module {m.no} · {m.title}</option>)}
          </select>
          <select className={s.select} value={topic} onChange={(e) => setTopic(e.target.value)} disabled={!module}>
            <option value="">All topics</option>
            {topicsOfModule.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <input className={s.input} placeholder="Search text…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <span className={st.muted}>{bank ? `${bank.length} question${bank.length === 1 ? '' : 's'}` : ''}</span>
        </div>
        <div className={`card ${st.bank}`}>
          {bank?.slice(0, 120).map((q) => (
            <div key={q.question_id} className={q.clean ? st.bankRow : st.bankRowFlag}>
              <div className={st.bankWhere}>{q.paper}<br />Q{q.number}{q.sub ?? ''} · {q.marks}m</div>
              <div>
                <MathText text={q.text} className={st.qText} />
                <Options options={q.options} />
                <div className={st.qMeta}>
                  {q.kind && <span className={st.chip}>{q.kind}</span>}
                  {q.topics.map((t) => <span key={t} className={st.topicChip}>{topicName(t)}</span>)}
                </div>
              </div>
            </div>
          ))}
          {bank && bank.length > 120 && <div className={st.muted}>Showing 120 of {bank.length}; narrow the filters.</div>}
          {bank?.length === 0 && <div className={st.muted}>No questions match.</div>}
        </div>
      </section>
    </>
  );
}

function MockView({ paper }: { paper: MockPaper }) {
  const { course, topicName } = useCourse();
  const items = paper.items ?? [];
  const partA = items.filter((i) => i.part === 'A');
  const mcq = course.template_id.includes('mcq');
  return (
    <article className={`card ${st.exam} ${st.printable}`}>
      <header className={st.examHead}>
        <div className="caps">Practice paper · seed {paper.seed}</div>
        <div className={st.examTitle}>{course.code} · {course.title}</div>
        <div className={st.examMeta}>Max. marks 100 · 3 hours · {paper.title}</div>
        <button className={st.linkBtn} onClick={() => window.print()}>print</button>
      </header>
      <div className={st.partHead}>{mcq ? 'QUESTIONS' : 'PART A'}</div>
      <div className={st.partSub}>{mcq ? `Answer all ${partA.length} questions. Each carries 1 mark; only one option is correct.` : 'Answer all questions. Each question carries 3 marks.'}</div>
      {partA.map((q) => (
        <div key={q.number} className={st.q}>
          <div className={st.qNum}>{q.number}</div>
          <div><MathText text={q.text} className={st.qText} /><Options options={q.options} /><div className={st.mockSource}>{q.source} · {q.topics.map(topicName).join(', ')}</div></div>
          <div className={st.qMarks}>({q.marks})</div>
        </div>
      ))}
      {!mcq && <div className={st.partHead}>PART B</div>}
      {!mcq && <div className={st.partSub}>Answer any one full question from each module. Each question carries 14 marks.</div>}
      {!mcq && course.modules.map((m) => {
        const qs = items.filter((i) => i.part === 'B' && i.module === m.no);
        const nums = [...new Set(qs.map((q) => q.number))].sort((a, b) => a - b);
        return (
          <section key={m.no}>
            <div className={st.moduleHead}>Module {m.no}</div>
            {nums.map((n, k) => (
              <div key={n}>
                {k > 0 && <div className={st.orLine}>OR</div>}
                {qs.filter((q) => q.number === n).map((q) => (
                  <div key={`${q.number}${q.sub}`} className={st.q}>
                    <div className={st.qNum}>{q.number}{q.sub ? ` (${q.sub})` : ''}</div>
                    <div><MathText text={q.text} className={st.qText} /><div className={st.mockSource}>{q.source}</div></div>
                    <div className={st.qMarks}>({q.marks})</div>
                  </div>
                ))}
              </div>
            ))}
          </section>
        );
      })}
    </article>
  );
}
