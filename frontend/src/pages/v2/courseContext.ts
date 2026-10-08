import { createContext, useContext } from 'react';
import type { CourseDetail, Coverage, JobParams, Snapshot } from '../../api/v2';

export interface CourseCtx {
  course: CourseDetail;
  snapshot: Snapshot | null;
  coverage: Coverage | null;
  topicName: (id: string) => string;
  refresh: () => void;
  runJob: (kind: 'acquire' | 'process' | 'insights' | 'notes', params?: JobParams) => Promise<void>;
  busy: boolean;
  version: number;
}

export const Ctx = createContext<CourseCtx | null>(null);
export const useCourse = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error('useCourse outside CourseWorkspace');
  return c;
};
