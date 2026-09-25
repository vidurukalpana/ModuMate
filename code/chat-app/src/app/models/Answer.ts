export type AnswerOrigin = 'local_qa' | 'simulated_fallback' | 'llm_fallback' | 'question_policy';

export interface AnswerSource {
  id: string;
  source: string;
  topic: string;
  chunk_index: number | null;
  excerpt: string;
}

export interface Answer {
  answer: string;
  source: AnswerOrigin;
  sources: AnswerSource[];
  cache_hit: boolean;
  reason?: string;
  suggested_topics?: string[];
  abstained?: boolean;
  simulated?: boolean;
}
