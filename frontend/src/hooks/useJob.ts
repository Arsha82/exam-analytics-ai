import { useEffect, useRef, useState } from 'react';
import { v2, type Job, type JobEvent } from '../api/v2';

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);

/**
 * Follows a job: polls its status and appends new events until it reaches a terminal state.
 * `onDone` fires once when the job finishes (any terminal status).
 * Mount one hook instance per job (key the component by job id).
 */
export function useJob(jobId: string | null, onDone?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const lastId = useRef(0);
  const doneRef = useRef(onDone);
  useEffect(() => {
    doneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    if (!jobId) return;
    lastId.current = 0;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const j = await v2.job(jobId, lastId.current);
        if (stopped) return;
        const fresh = j.events ?? [];
        if (fresh.length) {
          lastId.current = fresh[fresh.length - 1].id;
          setEvents((prev) => [...prev, ...fresh]);
        }
        setJob(j);
        if (TERMINAL.has(j.status)) {
          doneRef.current?.(j);
          return;
        }
      } catch {
        /* transient: keep polling */
      }
      timer = setTimeout(tick, 1500);
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  return { job, events, running: !!job && !TERMINAL.has(job.status) };
}
