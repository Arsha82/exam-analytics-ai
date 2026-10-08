import { useEffect, useState } from 'react';
import { v2, parseUtc, type Job } from '../../api/v2';
import JobCard from '../../components/v2/JobCard';
import { JOB_LABEL } from '../../components/v2/jobLabels';
import StatusMark from '../../components/bits/StatusMark';
import st from './v2.module.css';

const statusOf = (j: Job) =>
  j.status === 'succeeded' ? 'done' : j.status === 'failed' ? 'failed' : j.status === 'cancelled' ? 'cancelled' : 'running';

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    const load = () => v2.jobs({ limit: 100 }).then(setJobs).catch(() => setJobs([]));
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className={st.page}>
      <header>
        <h1>Jobs</h1>
        <p className={st.sectionHint}>Every agent run, with its full event log. Jobs survive page reloads; a server restart marks unfinished ones as interrupted.</p>
      </header>
      <div className={`card ${st.tableCard}`}>
        <table className={st.table}>
          <thead><tr><th /><th>Job</th><th>Course</th><th>Started</th><th>Result</th></tr></thead>
          <tbody>
            {jobs?.map((j) => (
              <tr key={j.id} onClick={() => setOpen(open === j.id ? null : j.id)} style={{ cursor: 'pointer' }}>
                <td><StatusMark status={statusOf(j)} progress={j.status === 'running' ? j.progress / 100 : undefined} size={16}
                  doneColor="var(--green)" errorColor="var(--red)" color="var(--ink-2)" /></td>
                <td>{JOB_LABEL[j.kind] ?? j.kind}<div className={st.mono}>{j.id}</div></td>
                <td className={st.mono}>{j.course_code}</td>
                <td className={st.num}>{parseUtc(j.started_at ?? j.created_at)?.toLocaleString()}</td>
                <td className={st.wrapCell}>{j.error ?? (j.result ? Object.entries(j.result).filter(([, v]) => typeof v !== 'object').map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(' · ') : j.status)}</td>
              </tr>
            ))}
            {jobs?.length === 0 && <tr><td colSpan={5} className={st.muted}>No jobs yet.</td></tr>}
          </tbody>
        </table>
      </div>
      {open && <JobCard key={open} jobId={open} />}
    </div>
  );
}
