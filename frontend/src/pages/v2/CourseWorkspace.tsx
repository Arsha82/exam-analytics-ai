import { useCallback, useEffect, useState } from 'react';
import { NavLink, useNavigate, useParams } from 'react-router-dom';
import { studyApi, v2, type CourseDetail, type Coverage, type Job, type JobParams, type Snapshot } from '../../api/v2';
import { Ctx } from './courseContext';
import JobCard from '../../components/v2/JobCard';
import StatusMark, { type StatusMarkStatus } from '../../components/bits/StatusMark';
import ShinyText from '../../components/bits/ShinyText';
import { COURSE_TABS } from './courseTabs';
import st from './v2.module.css';
import s from '../../design/shared.module.css';
import OverviewTab from './course/OverviewTab';
import SourcesTab from './course/SourcesTab';
import PapersTab from './course/PapersTab';
import InsightsTab from './course/InsightsTab';
import BacktestTab from './course/BacktestTab';
import PracticeTab from './course/PracticeTab';
import NotesTab from './course/NotesTab';
import LessonsTab from './course/LessonsTab';


const TABS = COURSE_TABS;

const STEPS: { kind: 'acquire' | 'process' | 'insights'; title: string; hint: string }[] = [
  { kind: 'acquire', title: 'Find papers', hint: 'Known repositories + agy web searches, downloaded and de-duplicated' },
  { kind: 'process', title: 'Read & analyse', hint: 'Local OCR, exam-template checks, agy only for flagged questions, topic tagging' },
  { kind: 'insights', title: 'Insights', hint: 'Appearance rates, prep sets and a backtest, recomputed from the data' },
];

function stepStatus(job?: Job): StatusMarkStatus {
  if (!job) return 'pending';
  if (job.status === 'running' || job.status === 'queued') return 'running';
  if (job.status === 'succeeded') return 'done';
  if (job.status === 'failed') return 'failed';
  return 'cancelled';
}

export default function CourseWorkspace() {
  const { code = '', tab = 'overview' } = useParams();
  const navigate = useNavigate();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [lastJobs, setLastJobs] = useState<Record<string, Job>>({});
  const [watching, setWatching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const load = useCallback(async () => {
    try {
      const [c, snap, cov, jobs] = await Promise.all([v2.course(code), v2.insights(code), v2.coverage(code), v2.jobs({ course: code, limit: 30 })]);
      setCourse(c);
      setSnapshot(snap);
      setCoverage(cov);
      const latest: Record<string, Job> = {};
      for (const j of jobs) if (!latest[j.kind]) latest[j.kind] = j;
      setLastJobs(latest);
      const running = jobs.find((j) => j.status === 'running' || j.status === 'queued');
      setWatching((w) => w ?? running?.id ?? null);
      setError(null);
    } catch (e: any) {
      setError(e?.response?.status === 404 ? `${code} has not been added yet.` : 'Could not reach the backend.');
    }
  }, [code]);

  useEffect(() => {
    load();
  }, [load, version]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  const start = async (kind: 'acquire' | 'process' | 'insights' | 'notes', params: JobParams = {}) => {
    const job = kind === 'acquire' ? await v2.acquire(code, params) : kind === 'process' ? await v2.process(code, params)
      : kind === 'notes' ? await v2.job((await studyApi.fetchNotes(code)).job_id) : await v2.recompute(code);
    setLastJobs((prev) => ({ ...prev, [kind]: job }));
    setWatching(job.id);
  };

  if (error) {
    return (
      <div className={`card ${st.cardPad}`}>
        <p>{error}</p>
        <button className={s.btnPrimary} style={{ marginTop: 12 }} onClick={() => navigate('/courses')}>Go to courses</button>
      </div>
    );
  }
  if (!course) return <span className="spinner" />;

  const topicIndex = new Map(course.modules.flatMap((m) => m.topics.map((t) => [t.id, t.name] as const)));
  const anyRunning = Object.values(lastJobs).some((j) => j.status === 'running' || j.status === 'queued');
  const nextStep = STEPS.find((x) => lastJobs[x.kind]?.status !== "succeeded")?.kind;

  return (
    <Ctx.Provider value={{ course, snapshot, coverage, topicName: (id) => topicIndex.get(id) ?? id, refresh, version, runJob: start, busy: anyRunning }}>
      <div className={st.page}>
        <header className={st.courseHeader}>
          <div className={st.courseCode}>{course.code}</div>
          <div style={{ flex: 1, minWidth: 280 }}>
            <h1 className={st.courseTitle}>{course.title}</h1>
            <div className={st.chips}>
              <span className={st.chip}>{course.university}</span>
              <span className={st.chip}>{course.scheme} scheme</span>
              {course.semester && <span className={st.chip}>Semester {course.semester}</span>}
              {course.slot && <span className={st.chip}>Slot {course.slot}</span>}
              {course.credits && <span className={st.chip}>{course.credits} credits</span>}
              <span className={st.chip}>{course.template_id.includes('mcq') ? '50 MCQs × 1 · 4 options' : 'Part A 10 × 3 · Part B 5 × 14'}</span>
            </div>
            {course.provisional && (
              <p className={st.provisional}>Topic list pending: built from the official syllabus when found, otherwise from this course's own past papers once they are read.</p>
            )}
          </div>
        </header>

        <nav className={st.tabs} role="tablist">
          {TABS.map((t) => (
            <NavLink key={t.key} to={`/courses/${code}/${t.key}`} role="tab"
              className={() => (tab === t.key ? st.tabActive : st.tab)}>
              {t.label}
            </NavLink>
          ))}
        </nav>

        {tab === 'overview' && (
          <section className={st.pipeline} aria-label="Pipeline">
            {STEPS.map((step, i) => {
              const job = lastJobs[step.kind];
              const status = stepStatus(job);
              return (
                <div key={step.kind} className={st.step}>
                  <div className={st.stepHead}>
                    <span className={st.stepNo}>{i + 1}</span>
                    <StatusMark status={status} progress={status === 'running' && job ? job.progress / 100 : undefined}
                      size={18} doneColor="var(--green)" errorColor="var(--red)" color="var(--ink-2)" />
                    <span className={st.stepTitle}>
                      {status === 'running' ? <ShinyText text={step.title} color="var(--ink-2)" shineColor="var(--paper-raised)" speed={2.4} /> : step.title}
                    </span>
                  </div>
                  <p className={st.stepHint}>{step.hint}</p>
                  <div className={st.row}>
                    <button className={step.kind === nextStep ? s.btnPrimary : s.btnGhost} disabled={anyRunning} onClick={() => start(step.kind)}>
                      {job ? 'Run again' : 'Run'}
                    </button>
                    {job && <span className={st.muted}>{summarize(job)}</span>}
                  </div>
                </div>
              );
            })}
          </section>
        )}

        {watching && <JobCard key={watching} jobId={watching} onDone={() => { refresh(); }} />}


        <div key={`${tab}-${version}`} className={st.tabBody}>
          {tab === 'overview' && <OverviewTab />}
          {tab === 'sources' && <SourcesTab />}
          {tab === 'papers' && <PapersTab />}
          {tab === 'insights' && <InsightsTab />}
          {tab === 'backtest' && <BacktestTab />}
          {tab === 'practice' && <PracticeTab />}
          {tab === 'lessons' && <LessonsTab />}
          {tab === 'notes' && <NotesTab />}
        </div>
      </div>
    </Ctx.Provider>
  );
}

const n = (v: number, word: string, plural = `${word}s`) => `${v} ${v === 1 ? word : plural}`;

function summarize(job: Job): string {
  const r = job.result as Record<string, any> | null | undefined;
  if (job.status === 'failed') return job.error ?? 'failed';
  if (!r) return job.status;
  if (job.kind === 'acquire') return `${n(r.fetched ?? 0, 'new file')} · ${n(r.duplicate ?? 0, 'duplicate')} · ${n(r.agy_queries ?? 0, 'search', 'searches')}`;
  if (job.kind === 'process') return `${n(r.distinct_papers ?? 0, 'paper')} · ${n(r.agy_repaired_slots ?? 0, 'agy repair')}`;
  return `${n(r.papers ?? 0, 'paper')} analysed`;
}
