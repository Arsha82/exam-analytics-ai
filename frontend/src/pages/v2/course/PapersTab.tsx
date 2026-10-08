import { useEffect, useMemo, useState } from 'react';
import { v2, type PaperQuestion, type PaperV2 } from '../../../api/v2';
import MathText from '../../../components/v2/MathText';
import Options from '../../../components/v2/Options';
import { useCourse } from '../courseContext';
import st from '../v2.module.css';
import s from '../../../design/shared.module.css';

const ISSUE_BADGE = { error: 'badge badge--danger', warn: 'badge badge--warning', info: 'badge badge--neutral' } as const;

export default function PapersTab() {
  const { course, version, refresh } = useCourse();
  const [papers, setPapers] = useState<PaperV2[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    v2.papers(course.code).then((p) => {
      setPapers(p);
      setSelected((cur) => cur ?? p[p.length - 1]?.paper_id ?? null);
    });
  }, [course.code, version]);

  if (!papers) return <span className="spinner" />;
  if (papers.length === 0) {
    return (
      <div className={`card ${st.empty}`}>
        <h2 className={st.emptyTitle}>No papers yet</h2>
        <p>Run <strong>Read &amp; analyse</strong> after finding papers. Each distinct question paper appears here once, however many files it came from.</p>
      </div>
    );
  }
  const paper = papers.find((p) => p.paper_id === selected) ?? papers[papers.length - 1];

  return (
    <div className={st.papersLayout}>
      <div className={st.paperList} role="listbox" aria-label="Papers">
        {papers.map((p) => {
          const errors = p.issues.filter((i) => i.level === 'error').length;
          const warns = p.issues.filter((i) => i.level === 'warn').length;
          return (
            <button key={p.paper_id} role="option" aria-selected={p.paper_id === paper.paper_id}
              className={p.paper_id === paper.paper_id ? st.paperItemActive : st.paperItem} onClick={() => setSelected(p.paper_id)}>
              <span>
                <span className={st.paperItemLabel}>{p.label}</span>
                <span className={st.paperItemSub}>{p.qp_code ? `QP …${p.qp_code.slice(-6)}` : 'no QP code'} · {p.questions.length} entries</span>
              </span>
              {errors > 0 ? <span className="badge badge--danger">{errors}</span> : warns > 0 ? <span className="badge badge--warning">{warns}</span> : <span className="badge badge--success">ok</span>}
            </button>
          );
        })}
      </div>
      <PaperView key={paper.paper_id} paper={paper} onChanged={refresh} />
    </div>
  );
}

function PaperView({ paper, onChanged }: { paper: PaperV2; onChanged: () => void }) {
  const { course, topicName, runJob, busy } = useCourse();
  const mcq = course.template_id.includes('mcq');
  const partA = paper.questions.filter((q) => q.part === 'A');
  const partB = paper.questions.filter((q) => q.part === 'B');
  const modules = course.modules.map((m) => m.no);

  return (
    <article className={`card ${st.exam}`}>
      <header className={st.examHead}>
        <div className="caps">{paper.qp_code ?? 'QP code not read'}</div>
        <div className={st.examTitle}>{paper.exam_title ?? paper.label}</div>
        <div className={st.examMeta}>
          {course.code} · {course.title} · Max. marks {paper.total_marks}
        </div>
        <div className={st.chips} style={{ justifyContent: 'center' }}>
          {paper.cohorts.map((c) => <span key={c} className={st.chip}>{c}</span>)}
          <span className={st.chip}>read by {paper.extraction_provider ?? '?'}</span>
          <button className={st.linkBtn} disabled={busy} title="Transcribe this paper again (local OCR with loop guards, agy for what is still flagged)"
            onClick={() => runJob('process', { paper_ids: [paper.paper_id] })}>re-read this paper</button>
        </div>
      </header>

      {paper.issues.length > 0 && (
        <div className={st.issues}>
          {paper.issues.map((i, n) => (
            <div key={n} className={st.issue}>
              <span className={ISSUE_BADGE[i.level]}>{i.code}</span>
              <span>{i.message}</span>
            </div>
          ))}
        </div>
      )}

      <div className={st.partHead}>{mcq ? 'QUESTIONS' : 'PART A'}</div>
      <div className={st.partSub}>{mcq ? 'Answer all questions. Each carries 1 mark; only one option is correct.' : 'Answer all questions. Each question carries 3 marks.'}</div>
      {partA.map((q) => <QuestionRow key={q.question_id} q={q} topicName={topicName} onChanged={onChanged} />)}

      {!mcq && <div className={st.partHead}>PART B</div>}
      {!mcq && <div className={st.partSub}>Answer any one full question from each module. Each question carries 14 marks.</div>}
      {!mcq && modules.map((m) => {
        const qs = partB.filter((q) => q.module === m);
        const numbers = [...new Set(qs.map((q) => q.number))].sort((a, b) => a - b);
        return (
          <section key={m}>
            <div className={st.moduleHead}>Module {m} · {course.modules.find((x) => x.no === m)?.title}</div>
            {numbers.length === 0 && <div className={st.muted}>Not transcribed.</div>}
            {numbers.map((n, idx) => (
              <div key={n}>
                {idx > 0 && <div className={st.orLine}>OR</div>}
                {qs.filter((q) => q.number === n).map((q) => <QuestionRow key={q.question_id} q={q} topicName={topicName} onChanged={onChanged} />)}
              </div>
            ))}
          </section>
        );
      })}

      <footer className={st.examFoot}>
        <div className="caps">Sources</div>
        {paper.sources.map((src) => (
          <div key={src.sha256} className={st.issue}>
            <span className={src.primary ? 'badge badge--info' : 'badge badge--neutral'}>{src.primary ? 'read' : 'copy'}</span>
            <span>{src.origin}{src.label_claimed ? ` — “${src.label_claimed.slice(0, 90)}”` : ''}</span>
            <a href={src.file_url} target="_blank" rel="noreferrer">open PDF</a>
          </div>
        ))}
      </footer>
    </article>
  );
}

function QuestionRow({ q, topicName, onChanged }: { q: PaperQuestion; topicName: (id: string) => string; onChanged: () => void }) {
  const { course } = useCourse();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(q.text);
  const [marks, setMarks] = useState(String(q.marks));
  const [topics, setTopics] = useState<string[]>(q.topics.map((t) => t.id));
  const [saving, setSaving] = useState(false);
  const moduleTopics = useMemo(() => course.modules.find((m) => m.no === q.module)?.topics ?? [], [course, q.module]);

  const save = async () => {
    setSaving(true);
    try {
      await v2.editQuestion(q.question_id, { text, marks: Number(marks), topics, resolved: true });
      setEditing(false);
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  const label = q.part === 'A' ? `${q.number}` : `${q.number}${q.sub ? ` (${q.sub})` : ''}`;
  return (
    <div className={q.needs_review ? st.qFlag : st.q}>
      <div className={st.qNum}>{label}</div>
      <div>
        {editing ? (
          <div className={st.stack}>
            <textarea className={st.editArea} value={text} onChange={(e) => setText(e.target.value)} aria-label="Question text (LaTeX between $...$)" />
            <div className={st.row}>
              <label className={st.muted}>Marks <input className={s.input} style={{ width: 64 }} value={marks} onChange={(e) => setMarks(e.target.value)} /></label>
            </div>
            <div className={st.row}>
              {moduleTopics.map((t) => (
                <label key={t.id} className={st.topicPick}>
                  <input type="checkbox" checked={topics.includes(t.id)}
                    onChange={(e) => setTopics((cur) => (e.target.checked ? [...cur, t.id] : cur.filter((x) => x !== t.id)))} />
                  {t.name}
                </label>
              ))}
            </div>
            <div className={st.row}>
              <button className={s.btnPrimary} onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save & mark checked'}</button>
              <button className={s.btnGhost} onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </div>
        ) : (
          <>
            <MathText text={q.text} className={st.qText} />
            <Options options={q.options} />
            <div className={st.qMeta}>
              {q.kind && <span className={st.chip}>{q.kind}</span>}
              {q.topics.map((t) => (
                <span key={t.id} className={t.source === 'keyword' ? st.topicChipWeak : st.topicChip} title={`${t.source}, ${Math.round(t.confidence * 100)}%`}>{topicName(t.id)}</span>
              ))}
              {q.has_diagram && <span className={st.chip}>diagram</span>}
              {q.needs_review && q.review_reason && <span className={st.flagNote}>{q.review_reason}</span>}
              <button className={st.linkBtn} onClick={() => setEditing(true)}>edit</button>
            </div>
          </>
        )}
      </div>
      <div className={st.qMarks} title={q.marks_inferred ? 'Not printed/readable — inferred from the exam template' : undefined}>({q.marks}){q.marks_inferred ? '*' : ''}</div>
    </div>
  );
}
