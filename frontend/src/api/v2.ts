/**
 * PYQ Analyzer v2 API client — courses, sources, papers, insights, jobs, system.
 */

import axios from 'axios';

const api = axios.create({ baseURL: '/api' });

/** Backend timestamps are naive UTC; make them parse as UTC. */
export function parseUtc(ts?: string | null): Date | null {
  if (!ts) return null;
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(ts) ? ts : `${ts}Z`);
}

export interface CatalogCourse {
  code: string;
  university: string;
  scheme: string;
  title: string;
  semester?: number;
  modules: number;
  topics: number;
}

export interface CourseSummary {
  code: string;
  title: string;
  university: string;
  scheme: string;
  semester?: number;
  credits?: number;
  papers: number;
  documents: number;
  coverage: { found: number; expected: number };
  last_analyzed?: string | null;
}

export interface TopicRef { id: string; name: string }
export interface ModuleDef { no: number; title: string; syllabus?: string; topics: TopicRef[] }

export interface CourseDetail {
  code: string;
  title: string;
  university: string;
  scheme: string;
  semester?: number;
  slot?: string;
  credits?: number;
  template_id: string;
  provisional?: boolean;
  syllabus_source?: string | null;
  modules: ModuleDef[];
  sources: { dspace?: string[]; pages?: string[] };
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface JobEvent {
  id: number;
  ts: string;
  level: 'info' | 'warn' | 'error';
  stage: string;
  message: string;
  data?: Record<string, unknown> | null;
}

export interface Job {
  id: string;
  kind: 'acquire' | 'process' | 'insights' | string;
  status: JobStatus;
  course_code?: string | null;
  progress: number;
  params: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  events?: JobEvent[];
}

export interface CoverageWindow {
  label: string;
  kind: 'regular' | 'supplementary';
  year: number;
  papers: { paper_id: string; label: string; qp_code?: string | null }[];
}

export interface Coverage {
  windows: CoverageWindow[];
  other: { paper_id: string; label: string; qp_code?: string | null }[];
  found: number;
  expected: number;
}

export interface SourceCandidate {
  id: number;
  url: string;
  page_url?: string | null;
  label?: string | null;
  found_by: string;
  status: 'new' | 'fetched' | 'duplicate' | 'failed' | 'skipped';
  reason?: string | null;
  sha256?: string | null;
}

export interface SourceDocument {
  sha256: string;
  url?: string | null;
  origin: string;
  label_claimed?: string | null;
  bytes: number;
  pages?: number | null;
  mime: string;
  status: string;
  identified: Record<string, any>;
  paper_id?: string | null;
  fetched_at: string;
  file_url: string;
}

export interface Issue {
  code: string;
  level: 'error' | 'warn' | 'info';
  message: string;
  number?: number | null;
  sub?: string | null;
}

export interface PaperQuestion {
  question_id: string;
  part: 'A' | 'B' | null;
  number: number;
  sub?: string | null;
  module?: number | null;
  marks: number;
  marks_inferred?: boolean;
  text: string;
  options?: string[] | null;
  kind?: string | null;
  legibility?: string | null;
  has_diagram: boolean;
  needs_review: boolean;
  review_reason?: string | null;
  topics: { id: string; confidence: number; source: string }[];
}

export interface PaperV2 {
  paper_id: string;
  label: string;
  session_month?: number | null;
  session_year?: number | null;
  exam_title?: string | null;
  cohorts: string[];
  qp_code?: string | null;
  scheme?: string | null;
  total_marks: number;
  extraction_provider?: string | null;
  extraction_model?: string | null;
  issues: Issue[];
  needs_review: boolean;
  sources: { sha256: string; origin: string; url?: string | null; label_claimed?: string | null; primary: boolean; file_url: string }[];
  questions: PaperQuestion[];
}

export interface TopicStat {
  topic_id: string;
  module: number;
  name: string;
  papers_with: number;
  appearance_rate: number;
  probability_next: number;
  probability_sd: number;
  part_a_rate: number;
  part_b_rate: number;
  total_marks: number;
  avg_marks_when_present: number;
  last_seen?: string | null;
  papers_since_last_seen?: number | null;
}

export interface PrepSet {
  k: number;
  topics: string[];
  full_coverage: number;
  expected_part_b_marks: number;
  part_a_marks: number;
}

export interface ModuleInsight {
  module: number;
  title: string;
  papers_evaluated: number;
  prep_sets: PrepSet[];
  kinds: { A: Record<string, number>; B: Record<string, number> };
}

export interface HeatCell {
  topic_id: string;
  paper_id: string;
  marks: number;
  part_a: number;
  part_b: number;
  questions: string[];
}

export interface RepeatCluster {
  relation: 'repeat' | 'template' | 'mixed';
  module: number;
  topics: string[];
  times: number;
  questions: { question_id: string; paper: string; number: number; sub?: string | null; marks: number; text: string }[];
}

export interface BacktestRow {
  paper_id: string;
  label: string;
  trained_on: number;
  topics_present: number;
  brier: { model: number; frequency: number; uniform: number };
  recall_at_k: { model: number | null; frequency: number | null };
  prep_set: Record<string, number | null>;
}

export interface Backtest {
  summary: {
    evaluated_papers: number;
    warmup: number;
    k: number;
    lambda: number;
    brier: { model: number | null; frequency: number | null; uniform: number | null };
    recall_at_k: { model: number | null; frequency: number | null };
    prep_set: Record<string, number | null>;
    verdict: string;
  };
  rows: BacktestRow[];
}

export interface Snapshot {
  id: number;
  computed_at: string;
  n_papers: number;
  papers: { paper_id: string; label: string; session_key: number }[];
  params: { lambda: number; alpha: number; beta: number; max_k: number };
  questions_total: number;
  questions_untagged: number;
  heatmap: HeatCell[];
  topics: TopicStat[];
  modules: ModuleInsight[];
  repeats: RepeatCluster[];
  backtest: Backtest;
  coverage: Coverage;
}

export interface SystemStatus {
  agy: { available: boolean; reason?: string | null; binary?: string | null; cooldown_seconds: number; agents: string[];
    models: Record<string, string>; concurrency: number };
  local_ocr: { available: boolean; reason?: string | null; model: string; num_ctx: number };
  podman: { available: boolean; binary?: string | null };
}

export interface JobParams { use_agy?: boolean; reprocess?: boolean; retag?: boolean; agy_repair_budget?: number; paper_ids?: string[]; broad?: boolean }

export const v2 = {
  catalog: async () => (await api.get<{ courses: CatalogCourse[] }>('/courses/catalog')).data.courses,
  courses: async () => (await api.get<{ courses: CourseSummary[] }>('/courses')).data.courses,
  addCourse: async (code: string) => (await api.post('/courses', { code })).data,
  course: async (code: string) => (await api.get<CourseDetail>(`/courses/${code}`)).data,
  coverage: async (code: string) => (await api.get<Coverage>(`/courses/${code}/coverage`)).data,
  sources: async (code: string) =>
    (await api.get<{ candidates: SourceCandidate[]; documents: SourceDocument[] }>(`/courses/${code}/sources`)).data,
  papers: async (code: string) => (await api.get<{ papers: PaperV2[] }>(`/courses/${code}/papers`)).data.papers,
  insights: async (code: string) => (await api.get<{ snapshot: Snapshot | null }>(`/courses/${code}/insights`)).data.snapshot,
  acquire: async (code: string, params: JobParams = {}) => (await api.post<Job>(`/courses/${code}/acquire`, params)).data,
  process: async (code: string, params: JobParams = {}) => (await api.post<Job>(`/courses/${code}/process`, params)).data,
  upload: async (code: string, files: File[], process = false) => {
    const fd = new FormData();
    // Keep the folder path (webkitRelativePath) so the source column shows where a file came from.
    for (const f of files) fd.append('files', f, (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name);
    return (await api.post<{ added: number; duplicates: number; skipped: string[]; job_id: string | null }>(
      `/courses/${code}/upload`, fd, { params: { process }, headers: { 'Content-Type': 'multipart/form-data' } })).data;
  },
  recompute: async (code: string) => (await api.post<Job>(`/courses/${code}/insights/recompute`)).data,
  editQuestion: async (id: string, body: { text?: string; marks?: number; topics?: string[]; kind?: string; resolved?: boolean }) =>
    (await api.patch(`/courses/questions/${encodeURIComponent(id)}`, body)).data,
  jobs: async (params: { course?: string; status?: string; limit?: number } = {}) =>
    (await api.get<{ jobs: Job[] }>('/jobs', { params })).data.jobs,
  job: async (id: string, after = 0) => (await api.get<Job>(`/jobs/${id}`, { params: { after } })).data,
  cancelJob: async (id: string) => (await api.post(`/jobs/${id}/cancel`)).data,
  system: async () => (await api.get<SystemStatus>('/system/status')).data,
};

// ── Profile & academics ──

export interface Profile {
  university: string;
  scheme: string;
  branch?: string | null;
  semester?: number | null;
  target_cgpa?: number | null;
  curriculum_branches: string[];
  known_branches: string[];
}

export interface SubjectRow {
  code: string;
  title: string;
  credits?: number | null;
  slot?: string | null;
  theory: boolean;
  added: boolean;
  papers?: number;
  provisional?: boolean;
}

export interface Backlog {
  course_code: string;
  title?: string | null;
  semester?: number | null;
  credits: number;
  grade: string;
  attempts: number;
  added?: boolean;
  papers?: number;
}

export interface AcademicRecordRow {
  id: number;
  course_code: string;
  title?: string | null;
  grade: string;
  semester?: number | null;
  credits?: number | null;
  session_label?: string | null;
  source: string;
  failed: boolean;
}

export interface Academics {
  semesters: { semester: number; sgpa: number | null; credits_registered: number; credits_earned: number; courses: number }[];
  cgpa: number | null;
  credits_earned: number;
  credits_registered: number;
  backlogs: Backlog[];
  records: AcademicRecordRow[];
  grade_points: Record<string, number>;
  target?: { target_cgpa: number; next_semester: number; next_credits: number; needed_sgpa: number | null };
}

export interface ParsedCard {
  source_sha: string;
  session?: string | null;
  records: { course_code: string; title?: string | null; grade: string; credits?: number | null; semester?: number | null }[];
  text_chars: number;
}

// ── Practice & lessons ──

export interface BankRow {
  question_id: string;
  paper: string;
  part: 'A' | 'B';
  number: number;
  sub?: string | null;
  module: number;
  marks: number;
  text: string;
  options?: string[] | null;
  topics: string[];
  kind?: string | null;
  clean: boolean;
}

export interface MockItem {
  number: number;
  sub?: string | null;
  part: 'A' | 'B';
  module: number;
  marks: number;
  text: string;
  options?: string[] | null;
  topics: string[];
  kind?: string | null;
  question_id: string;
  source: string;
}

export interface MockPaper {
  id: number;
  title: string;
  seed: number;
  params: { focus?: string };
  created_at: string;
  items?: MockItem[];
  questions?: number;
}

export interface NoteDoc {
  sha256: string;
  title?: string | null;
  module?: number | null;
  url?: string | null;
  origin: string;
  pages?: number | null;
  bytes: number;
  file_url: string;
}

export interface DeckSlide {
  kind: string;
  heading: string;
  bullets: string[];
  latex?: string | null;
  narration: string;
  ref?: string | null;
}

export interface Deck {
  title: string;
  slides: DeckSlide[];
  quiz: { q: string; answer: string }[];
}

export interface LessonRow {
  id: number;
  course_code: string;
  topic_id: string;
  status: 'queued' | 'ready' | 'failed';
  deck?: Deck | null;
  video_status?: string | null;
  has_video: boolean;
  error?: string | null;
}

export const profileApi = {
  get: async () => (await api.get<Profile>('/profile')).data,
  save: async (body: { branch?: string; semester?: number; target_cgpa?: number }) => (await api.put<Profile>('/profile', body)).data,
  curriculum: async (branch: string) =>
    (await api.get<{ branch: string; courses: { semester: number; slot?: string; code: string; title: string; ltp?: string; credits?: number }[] }>(
      '/profile/curriculum', { params: { branch } })).data,
  subjects: async () =>
    (await api.get<{ semester?: number; branch?: string; current: SubjectRow[]; backlogs: Backlog[]; catalog_codes: string[] }>('/profile/subjects')).data,
  addSubjects: async (codes: string[], auto = true) =>
    (await api.post<{ started: { code: string; job_id: string | null; kind: string | null }[] }>('/profile/subjects/add', { codes, auto })).data,
  academics: async () => (await api.get<Academics>('/profile/academics')).data,
  uploadGradeCard: async (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return (await api.post<ParsedCard>('/profile/grade-card', fd, { headers: { 'Content-Type': 'multipart/form-data' } })).data;
  },
  saveRecords: async (records: { course_code: string; grade: string; title?: string | null; semester?: number | null; credits?: number | null; session_label?: string | null }[], source = 'manual', source_sha?: string) =>
    (await api.post('/profile/records', { records, source, source_sha })).data,
  deleteRecord: async (id: number) => api.delete(`/profile/records/${id}`),
};

export const studyApi = {
  questions: async (code: string, params: { module?: number; topic?: string; kind?: string; part?: string; q?: string } = {}) =>
    (await api.get<{ total: number; questions: BankRow[] }>(`/study/${code}/questions`, { params })).data,
  createMock: async (code: string, focus: string) => (await api.post<MockPaper>(`/study/${code}/mock-papers`, { focus })).data,
  mocks: async (code: string) => (await api.get<{ mock_papers: MockPaper[] }>(`/study/${code}/mock-papers`)).data.mock_papers,
  mock: async (id: number) => (await api.get<MockPaper>(`/study/mock-papers/${id}`)).data,
  notes: async (code: string) => (await api.get<{ notes: NoteDoc[] }>(`/study/${code}/notes`)).data.notes,
  fetchNotes: async (code: string) => (await api.post<{ job_id: string }>(`/study/${code}/notes/fetch`)).data,
  lessons: async (code: string) =>
    (await api.get<{ topics: { topic_id: string; name: string; module: number; lesson: LessonRow | null }[] }>(`/study/${code}/lessons`)).data.topics,
  createLesson: async (code: string, topic_id: string) =>
    (await api.post<{ lesson_id: number; job_id: string }>(`/study/${code}/lessons`, { topic_id })).data,
  lesson: async (id: number) => (await api.get<LessonRow>(`/study/lessons/${id}`)).data,
  renderVideo: async (id: number, voice?: string) => (await api.post<{ job_id: string }>(`/study/lessons/${id}/video`, voice ? { voice } : {})).data,
  videoUrl: (id: number) => `/api/study/lessons/${id}/video`,
};

// ── Library: gather papers for any subject (Home) ──
export interface LibraryState {
  pending: number;
  other_subjects: { code: string; title: string | null; papers: number }[];
  unidentified: { sha256: string; name: string | null; pages: number | null; file_url: string }[];
  not_papers: number;
  jobs: Job[];
}

export const libraryApi = {
  get: async () => (await api.get<LibraryState>('/library')).data,
  upload: async (files: File[]) => {
    const fd = new FormData();
    // Keep the folder path (webkitRelativePath) so the file name still says where it came from.
    for (const f of files) fd.append('files', f, (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name);
    return (await api.post<{ added: number; duplicates: number; skipped: string[]; job: Job | null }>(
      '/library/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })).data;
  },
  search: async (query?: string) => (await api.post<Job>('/library/search', { query: query || null })).data,
  adopt: async (code: string, sha256?: string) =>
    (await api.post<{ code: string; title: string; moved: number; job: Job }>('/library/adopt', { code, sha256 })).data,
};
