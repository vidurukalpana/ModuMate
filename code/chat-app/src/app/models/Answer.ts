export type AnswerOrigin =
  | 'local_qa'
  | 'llm_fallback'
  | 'simulated_fallback'
  | 'question_policy';

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
  cache_match_type?: 'exact' | 'semantic';
  cache_similarity?: number;
  cache_matched_question?: string;
  // Local QA only: the extracted span inside the full-sentence answer.
  answer_span?: string;
  reason?: string;
  suggested_topics?: string[];
  abstained?: boolean;
  simulated?: boolean;
}
