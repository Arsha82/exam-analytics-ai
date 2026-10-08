import { useEffect, useRef } from 'react';
import { v2, parseUtc, type Job } from '../../api/v2';
import { useJob } from '../../hooks/useJob';
import { JOB_LABEL } from './jobLabels';
import st from '../../pages/v2/v2.module.css';
import s from '../../design/shared.module.css';

const STATUS_BADGE: Record<string, string> = {
  queued: 'badge badge--neutral',
  running: 'badge badge--info',
  succeeded: 'badge badge--success',
  failed: 'badge badge--danger',
  cancelled: 'badge badge--warning',
};


/** Live view of one job: status, progress and its event log. */
export default function JobCard({ jobId, onDone, compact = false }: { jobId: string; onDone?: (j: Job) => void; compact?: boolean }) {
  const { job, events, running } = useJob(jobId, onDone);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events.length]);

  if (!job) {
    return (
      <div className={`card ${st.jobCard}`}>
        <span className="spinner" />
      </div>
    );
  }
  const fill = job.status === 'failed' ? st.progressFillFail : job.status === 'succeeded' ? st.progressFillDone : st.progressFill;
  const started = parseUtc(job.started_at);
  const finished = parseUtc(job.finished_at);
  const secs = started ? Math.round(((finished ?? new Date()).getTime() - started.getTime()) / 1000) : 0;

  return (
    <div className={`card ${st.jobCard}`}>
      <div className={st.row}>
        <span className={st.jobTitle}>{JOB_LABEL[job.kind] ?? job.kind}</span>
        <span className={STATUS_BADGE[job.status]}>{job.status}</span>
        <span className={st.muted}>{job.course_code} · {secs >= 60 ? `${Math.floor(secs / 60)}m ${secs % 60}s` : `${secs}s`}</span>
        <span className={st.spacer} />
        {running && (
          <button className={`${s.btnGhost} ${s.btnSm}`} onClick={() => v2.cancelJob(job.id)}>
            Cancel
          </button>
        )}
      </div>
      <div className={st.progress} role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}>
        <div className={fill} style={{ width: `${job.status === 'succeeded' ? 100 : job.progress}%` }} />
      </div>
      {job.error && <div className={st.logError}>{job.error}</div>}
      {!compact && (
        <div className={st.log} ref={logRef}>
          {events.map((e) => (
            <div key={e.id} className={`${st.logLine} ${e.level === 'warn' ? st.logWarn : e.level === 'error' ? st.logError : ''}`}>
              <span className={st.logStage}>{e.stage}</span>
              <span>{e.message}</span>
            </div>
          ))}
          {events.length === 0 && <div className={st.muted}>Waiting for events…</div>}
        </div>
      )}
    </div>
  );
}
