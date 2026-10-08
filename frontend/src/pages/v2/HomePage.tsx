import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { v2, parseUtc, type CatalogCourse, type CourseSummary, type Job } from '../../api/v2';
import CountUp from '../../components/bits/CountUp';
import SpotlightCard from '../../components/bits/SpotlightCard';
import StatusMark from '../../components/bits/StatusMark';
import GatherPanel from '../../components/v2/GatherPanel';
import { JOB_LABEL } from '../../components/v2/jobLabels';
import st from './v2.module.css';
import s from '../../design/shared.module.css';

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? 'Late night' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

const statusOf = (j: Job) =>
  j.status === 'succeeded' ? 'done' : j.status === 'failed' ? 'failed' : j.status === 'cancelled' ? 'cancelled' : 'running';

export default function HomePage() {
  const [courses, setCourses] = useState<CourseSummary[] | null>(null);
  const [catalog, setCatalog] = useState<CatalogCourse[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);

  useEffect(() => {
    v2.courses().then(setCourses).catch(() => setCourses([]));
    v2.catalog().then(setCatalog).catch(() => setCatalog([]));
    v2.jobs({ limit: 6 }).then(setJobs).catch(() => setJobs([]));
  }, []);

  const add = async (code: string) => {
    await v2.addCourse(code);
    setCourses(await v2.courses());
  };

  const totalPapers = courses?.reduce((a, c) => a + c.papers, 0) ?? 0;
  const notAdded = catalog.filter((c) => !courses?.some((x) => x.code === c.code));

  return (
    <div className={st.page}>
      <header className={st.homeHead}>
        <div className="caps">{new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}</div>
        <h1 className={st.homeTitle}>{greeting()}.</h1>
        <p className={st.homeLede}>
          {courses && courses.length > 0 ? (
            <>You are tracking <strong>{courses.length}</strong> subject{courses.length === 1 ? '' : 's'} with{' '}
              <strong><CountUp to={totalPapers} duration={1} /></strong> past papers read and checked.</>
          ) : (
            <>Drop in question papers or search for them below — the app files each under its subject, reads it and shows what actually gets asked.</>
          )}
        </p>
      </header>

      <GatherPanel onFiled={() => v2.courses().then(setCourses).catch(() => undefined)} />

      <section className={st.stack}>
        <div className={st.sectionTitle}>Your subjects</div>
        <div className={st.courseGrid}>
          {courses?.map((c) => (
            <Link key={c.code} to={`/courses/${c.code}`} className={st.cardLink}>
              <SpotlightCard className={st.courseCard} spotlightColor="rgba(31, 74, 115, 0.08)">
                <div className={st.row}>
                  <span className={st.courseCode}>{c.code}</span>
                  <span className={st.muted}>{c.university} · {c.scheme} · S{c.semester}</span>
                </div>
                <div className={st.courseCardTitle}>{c.title}</div>
                <div className={st.cardStats}>
                  <span><strong className="display-num">{c.papers}</strong> papers</span>
                  <span><strong className="display-num">{c.coverage.found}/{c.coverage.expected}</strong> sessions</span>
                  <span><strong className="display-num">{c.documents}</strong> files</span>
                </div>
                <div className={st.muted}>
                  {c.last_analyzed ? `Analysed ${parseUtc(c.last_analyzed)?.toLocaleString()}` : 'Not analysed yet'}
                </div>
              </SpotlightCard>
            </Link>
          ))}
          {notAdded.map((c) => (
            <div key={c.code} className={`card ${st.courseCard} ${st.addCard}`}>
              <div className={st.row}>
                <span className={st.courseCode}>{c.code}</span>
                <span className={st.muted}>{c.university} · {c.scheme} · {c.modules} modules · {c.topics} topics</span>
              </div>
              <div className={st.courseCardTitle}>{c.title}</div>
              <button className={s.btnPrimary} onClick={() => add(c.code)}>Add subject</button>
            </div>
          ))}
        </div>
      </section>

      <section className={st.stack}>
        <div className={st.row}>
          <div className={st.sectionTitle}>Recent activity</div>
          <span className={st.spacer} />
          <Link to="/jobs" className={st.muted}>All jobs →</Link>
        </div>
        <div className={`card ${st.activity}`}>
          {jobs.length === 0 && <div className={st.muted}>Nothing has run yet.</div>}
          {jobs.map((j) => (
            <div key={j.id} className={st.activityRow}>
              <StatusMark status={statusOf(j)} progress={j.status === 'running' ? j.progress / 100 : undefined} size={16}
                doneColor="var(--green)" errorColor="var(--red)" color="var(--ink-2)" />
              <span className={st.activityTitle}>{JOB_LABEL[j.kind] ?? j.kind}</span>
              <span className={st.mono}>{j.course_code}</span>
              <span className={st.spacer} />
              <span className={st.muted}>{parseUtc(j.created_at)?.toLocaleString()}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
