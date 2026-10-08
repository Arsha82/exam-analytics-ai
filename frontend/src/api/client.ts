/**
 * PYQ Analyzer — Frontend API Client.
 * Connects React UI to FastAPI endpoints with zero mock data.
 */

import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

export interface Paper {
  paper_id: string;
  subject: string;
  year: number;
  total_marks: number;
  source_file: string;
  ocr_status: 'pending' | 'processing' | 'completed' | 'failed';
  needs_review: boolean;
  question_count: number;
  created_at: string;
}

export interface Question {
  question_id: string;
  paper_id: string;
  year: number;
  question_no: string;
  text: string;
  marks: number;
  has_diagram: boolean;
  diagram_ref?: string;
  or_choice_group?: string;
  unit_guess?: string;
  unit_confidence?: number;
  reasoning?: string;
  needs_review: boolean;
  review_reason?: string;
  created_at: string;
}

export interface TopicFrequency {
  unit: string;
  count: number;
  pct_of_total: number;
}

export interface MarkWeight {
  unit: string;
  total_marks: number;
  pct_of_total_marks: number;
}

export interface YearTrend {
  unit: string;
  year: number;
  count: number;
  mark_share_pct: number;
  trend: 'rising' | 'declining' | 'stable';
}

export interface TwistedPair {
  question_id_a: string;
  question_id_b: string;
  similarity: number;
  verdict: string;
  reasoning?: string;
}

export interface ClusterItem {
  cluster_id: number;
  label: string;
  question_ids: string[];
}

export interface AnalysisResults {
  subject: string;
  frequency: TopicFrequency[];
  mark_weights: MarkWeight[];
  trends: YearTrend[];
  clusters: ClusterItem[];
  twisted_pairs: TwistedPair[];
}

export interface RubricItem {
  point: string;
  weight: number;
}

export interface PredictedQuestion {
  question_no: string;
  unit: string;
  text: string;
  marks: number;
  source: string;
  similarity_flag?: string;
  rubric?: RubricItem[];
}

export interface PredictedPaper {
  predicted_paper_id: string;
  subject: string;
  target_marks: number;
  variant: number;
  parent_paper_id?: string;
  question_count?: number;
  generated_at: string;
  questions?: PredictedQuestion[];
}

export interface AttemptScore {
  id: number;
  question_id: string;
  marks_awarded: number;
  max_marks: number;
  missing_points?: string[];
  checklist_results?: Record<string, string>;
  reasoning: string;
  low_confidence: boolean;
}

export interface Attempt {
  attempt_id: string;
  predicted_paper_id: string;
  student_id: string;
  ocr_status: string;
  total_marks_awarded?: number;
  total_max_marks?: number;
  score_pct?: number;
  submitted_at: string;
  scores?: AttemptScore[];
}

export interface MasteryItem {
  unit: string;
  subject: string;
  score_pct: number;
  bucket: 'weak' | 'partial' | 'clear';
  attempt_count: number;
  last_updated?: string;
}

export interface MasteryResponse {
  student_id: string;
  subject?: string;
  overall_readiness_pct: number;
  topic_mastery: MasteryItem[];
  weak_topics: string[];
  partial_topics: string[];
  clear_topics: string[];
  recommended_focus: string[];
}

export interface ReviewItem {
  id: string;
  type: 'paper' | 'question' | 'attempt_score';
  title: string;
  reason: string;
  subject?: string;
  year?: number;
  unit?: string;
  marks?: number;
  text?: string;
  marks_awarded?: number;
  max_marks?: number;
  reasoning?: string;
  created_at?: string;
}

export interface PipelineEvent {
  agent: string;
  stage: string;
  progress: number;
  detail: string;
  timestamp: string;
}

export const apiClient = {
  // Health
  checkHealth: async () => {
    const res = await api.get('/health');
    return res.data;
  },

  // Papers
  getPapers: async (params?: { subject?: string; year?: number; status?: string }) => {
    const res = await api.get<{ papers: Paper[]; total: number }>('/papers', { params });
    return res.data;
  },

  getPaper: async (paperId: string) => {
    const res = await api.get<Paper>(`/papers/${paperId}`);
    return res.data;
  },

  uploadPaper: async (formData: FormData) => {
    const res = await api.post<Paper>('/papers/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return res.data;
  },

  rerunOcr: async (paperId: string) => {
    const res = await api.post(`/papers/${paperId}/rerun-ocr`);
    return res.data;
  },

  deletePaper: async (paperId: string) => {
    await api.delete(`/papers/${paperId}`);
  },

  // Questions
  getQuestions: async (params?: { subject?: string; year?: number; unit?: string; needs_review?: boolean; skip?: number; limit?: number }) => {
    const res = await api.get<{ questions: Question[]; total: number }>('/questions', { params });
    return res.data;
  },

  getQuestion: async (questionId: string) => {
    const res = await api.get<Question>(`/questions/${questionId}`);
    return res.data;
  },

  updateQuestion: async (questionId: string, update: Partial<Question>) => {
    const res = await api.patch<Question>(`/questions/${questionId}`, update);
    return res.data;
  },

  // Syllabus
  getSyllabus: async (subject?: string) => {
    const res = await api.get<{ subject?: string; units: any[]; total_nodes: number }>('/syllabus', {
      params: { subject },
    });
    return res.data;
  },

  importSyllabus: async (subject: string, nodes: Array<{ unit: string; topic: string; sub_topic?: string; description: string }>) => {
    const res = await api.post('/syllabus/import', { subject, nodes });
    return res.data;
  },

  reembedSyllabus: async (subject?: string) => {
    const res = await api.post('/syllabus/reembed', null, { params: { subject } });
    return res.data;
  },

  deleteSyllabusNode: async (nodeId: string) => {
    await api.delete(`/syllabus/nodes/${nodeId}`);
  },

  // Analysis
  getAnalysisSummary: async (subject: string) => {
    const res = await api.get<AnalysisResults>('/analysis/summary', { params: { subject } });
    return res.data;
  },

  runAnalysis: async (subject: string) => {
    const res = await api.post<AnalysisResults>('/analysis/run', null, { params: { subject } });
    return res.data;
  },

  // Predictions
  getPredictions: async (subject?: string) => {
    const res = await api.get<{ predictions: PredictedPaper[]; total: number }>('/predictions', {
      params: { subject },
    });
    return res.data;
  },

  getPrediction: async (predictedPaperId: string) => {
    const res = await api.get<PredictedPaper>(`/predictions/${predictedPaperId}`);
    return res.data;
  },

  generatePrediction: async (subject: string, targetMarks: number = 100, variantCount: number = 1, studentId?: string) => {
    const res = await api.post('/predictions/generate', null, {
      params: { subject, target_marks: targetMarks, variant_count: variantCount, student_id: studentId },
    });
    return res.data;
  },

  // Attempts
  uploadAttempt: async (formData: FormData) => {
    const res = await api.post('/attempts/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return res.data;
  },

  getAttempts: async (studentId: string = 'default') => {
    const res = await api.get<{ attempts: Attempt[]; total: number }>('/attempts', {
      params: { student_id: studentId },
    });
    return res.data;
  },

  getAttempt: async (attemptId: string) => {
    const res = await api.get<Attempt>(`/attempts/${attemptId}`);
    return res.data;
  },

  reEvaluateAttempt: async (attemptId: string) => {
    const res = await api.post(`/attempts/${attemptId}/re-evaluate`);
    return res.data;
  },

  // Mastery
  getMastery: async (studentId: string = 'default', subject?: string) => {
    const res = await api.get<MasteryResponse>('/mastery', {
      params: { student_id: studentId, subject },
    });
    return res.data;
  },

  resetMastery: async (studentId: string = 'default', subject?: string) => {
    const res = await api.post('/mastery/reset', null, {
      params: { student_id: studentId, subject },
    });
    return res.data;
  },

  // Review Queue
  getReviewQueue: async () => {
    const res = await api.get<{ items: ReviewItem[]; total: number }>('/pipeline/review-queue');
    return res.data;
  },

  resolveReviewItem: async (itemType: string, itemId: string, payload?: any) => {
    const res = await api.patch(`/pipeline/review-queue/${itemType}/${itemId}`, payload);
    return res.data;
  },

  // WebSocket
  createPipelineWebSocket: (onMessage: (event: PipelineEvent) => void) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/pipeline/ws`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.agent && data.stage) {
          onMessage(data as PipelineEvent);
        }
      } catch (err) {
        // ignore non-json
      }
    };

    return ws;
  },
};
