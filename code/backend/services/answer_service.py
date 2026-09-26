"""One bounded response cache shared by extractive QA and LLM answers."""

from copy import deepcopy
import math
import re
from threading import Lock

from services.question_answering import (
    NoAnswerFound, ServiceUnavailable, clear_retrieval_trace,
    get_retrieval_trace, get_retrieved_passages, mark_cache_hit, record_question_policy,
)
from services.llm_fallback import FallbackError
from utilities.cache_lfu import CacheLFU
from services.question_policy import QuestionPolicy
from services.cache_version import active_version
from services.observability import stage
from services.concurrency import ConcurrencyConfig, WorkCoordinator
from services.semantic_cache import SemanticCacheConfig, compatible, cosine

# Extractive QA returns a short span; these questions ask for an explanation instead.
EXPLANATORY_QUESTION = re.compile(
    r"^\s*(what\s+(is|are|was|were|does|do)|explain|describe|define|how\s+(is|are|does|do)|why)\b",
    re.IGNORECASE,
)
# Short factual questions are fully answered by the extracted span.
SHORT_FACT_QUESTION = re.compile(
    r"\b(stand\s+for|full\s+form|abbreviation|acronym)\b|^\s*how\s+(many|much)\b",
    re.IGNORECASE,
)


class AnswerService:
    def __init__(self, question_service, fallback_service, *, question_policy=None, cache_capacity=4, semantic_config=None, cache_ttl=None, concurrency_config=None):
        self.question_service = question_service
        self.fallback_service = fallback_service
        self._policy = question_policy if question_policy is not None else QuestionPolicy()
        self._cache = CacheLFU(capacity=cache_capacity, ttl_seconds=cache_ttl)
        self._lock = Lock()
        self._semantic = semantic_config or SemanticCacheConfig()
        self._version_lock = Lock()
        self._version = None
        self._generation = 0
        self.concurrency = WorkCoordinator(concurrency_config or ConcurrencyConfig())

    def answer(self, question, category):
        clear_retrieval_trace()
        with self.concurrency.admit():
            self._refresh_version()
            with stage("cache_lookup"), self._lock:
                generation = self._generation
                if self._cache.contains((category, question)):
                    cached = self._cache.get((category, question))
                    mark_cache_hit()
                    return {**deepcopy(cached), "cache_hit": True, "cache_match_type": "exact"}
            return self.concurrency.run(
                (category, question, generation),
                lambda: self._answer(question, category, generation),
            )

    def _answer(self, question, category, generation):
        try:
            decision = self._policy.before_answer(question)
        except (OSError, ValueError) as error:
            raise ServiceUnavailable() from error
        if decision:
            record_question_policy(decision["reason"])
            return decision
        key = (category, question)
        with stage("cache_lookup"), self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                mark_cache_hit()
                return {**deepcopy(cached), 'cache_hit': True, 'cache_match_type': 'exact'}
        vector = None
        if self._semantic.enabled:
            with stage("semantic_matching"):
                with self._lock:
                    candidates = [(candidate, answer, _vector(embedding))
                                  for candidate, answer, embedding in self._cache.candidates(category)
                                  if compatible(question, candidate[1])]
                candidates = [c for c in candidates if c[2] is not None]
                if candidates:
                    vector = self._embed(question)
                    scored = [(cosine(vector, embedding), candidate, answer)
                              for candidate, answer, embedding in candidates] if vector else []
                    # Highest similarity wins; it must be strictly above the threshold.
                    scored = sorted((item for item in scored if item[0] is not None),
                                    key=lambda item: item[0], reverse=True)
                    if scored and scored[0][0] > self._semantic.threshold:
                        score, candidate, expected = scored[0]
                        with self._lock:
                            cached = self._cache.semantic_hit(candidate, expected)
                        if cached is not None:
                            mark_cache_hit()
                            return {**deepcopy(cached), 'cache_hit': True,
                                    'cache_match_type': 'semantic', 'cache_similarity': score,
                                    'cache_matched_question': candidate[1]}
        try:
            response = self._explain(question, category, self.question_service.answer(question))
            cacheable = True
        except NoAnswerFound as error:
            decision = self._policy.after_retrieval(error.reason, get_retrieval_trace())
            if decision:
                record_question_policy(decision["reason"])
                return decision
            response = self.fallback_service.respond(question, category, error.reason, error.passages)
            cacheable = (
                response.get('source') == 'llm_fallback'
                and response.get('simulated') is False
                and bool(response.get('sources'))
                and isinstance(response.get('answer'), str) and bool(response['answer'].strip())
                and not response.get('abstained')
            )
        self._refresh_version()
        if cacheable:
            if self._semantic.enabled and vector is None:
                vector = self._embed(question)
            with self._lock:
                if generation == self._generation:
                    self._cache.put(key, deepcopy(response), vector)
        return {**response, 'cache_hit': False}

    def _explain(self, question, category, extracted):
        """Prefer a course-grounded Ollama explanation, keeping the extracted answer if it fails."""
        if getattr(getattr(self.fallback_service, 'config', None), 'mode', None) != 'ollama':
            return extracted
        if not EXPLANATORY_QUESTION.match(question) or SHORT_FACT_QUESTION.search(question):
            return extracted
        try:
            generated = self.fallback_service.respond(
                question, category, 'explanation_requested', get_retrieved_passages())
        except FallbackError:
            return extracted
        if generated.get('abstained'):
            return extracted
        # Local QA did answer; the LLM only expanded it, so this is not a fallback.
        explained = {**generated, 'source': 'llm_explanation', 'extracted_answer': extracted['answer']}
        explained.pop('fallback_reason', None)
        return explained

    def _embed(self, question):
        """Encode one question with the shared MiniLM model; None if unusable."""
        with stage("semantic_encoding"):
            vectors = self.question_service.encode_questions([question])
        try:
            return _vector(vectors[0])
        except (TypeError, IndexError, KeyError):
            return None

    def cache_stats(self):
        with self._lock:
            return {**self._cache.stats(), 'semantic_enabled': self._semantic.enabled,
                    'semantic_threshold': self._semantic.threshold}

    def cache_rows(self):
        with self._lock:
            return self._cache.rows()

    def clear_cache(self, reason='manual'):
        with self._lock:
            self._generation += 1
            return self._cache.clear(reason)

    def _refresh_version(self):
        # Never hold the cache lock while waiting for model initialization/inference.
        with stage("cache_version_check"), self._version_lock:
            try:
                version = active_version(self.question_service, self.fallback_service, self._semantic)
            except (OSError, ValueError) as error:
                self.clear_cache('materials_unavailable')
                raise ServiceUnavailable() from error
            if self._version is not None and version != self._version:
                reason = 'materials_changed' if version[0] != self._version[0] else 'configuration_changed'
                self.clear_cache(reason)
                self.question_service.reset()
                self._policy.reset()
            self._version = version


def _vector(value):
    """Return a finite float list, or None for missing or malformed embeddings."""
    if value is None:
        return None
    try:
        vector = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    return vector if vector and all(math.isfinite(v) for v in vector) else None
