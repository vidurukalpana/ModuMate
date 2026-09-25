"""One bounded response cache shared by extractive QA and LLM answers."""

from copy import deepcopy
from threading import Lock

from services.question_answering import (
    NoAnswerFound, ServiceUnavailable, clear_retrieval_trace,
    get_retrieval_trace, mark_cache_hit, record_question_policy,
)
from utilities.cache_lfu import CacheLFU
from services.question_policy import QuestionPolicy
from services.cache_version import active_version
from services.observability import stage
from services.semantic_cache import SemanticCacheConfig, compatible, cosine


class AnswerService:
    def __init__(self, question_service, fallback_service, *, question_policy=None, cache_capacity=10, semantic_config=None, cache_ttl=3600):
        self.question_service = question_service
        self.fallback_service = fallback_service
        self._policy = question_policy if question_policy is not None else QuestionPolicy()
        self._cache = CacheLFU(capacity=cache_capacity, ttl_seconds=cache_ttl)
        self._lock = Lock()
        self._semantic = semantic_config or SemanticCacheConfig()
        self._version_lock = Lock()
        self._version = None
        self._generation = 0

    def answer(self, question, category):
        self._refresh_version()
        with self._lock:
            generation = self._generation
        clear_retrieval_trace()
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
        if self._semantic.enabled:
            with stage("semantic_matching"):
                with self._lock:
                    candidates = [(candidate, answer) for candidate, answer in self._cache.candidates(category)
                                  if compatible(question, candidate[1])]
                if candidates:
                    with stage("semantic_encoding"):
                        vectors = self.question_service.encode_questions([question] + [key[1] for key, _ in candidates])
                    scores = [cosine(vectors[0], vector) for vector in vectors[1:]]
                    ranked = sorted(zip(candidates, scores), key=lambda item: item[1] if item[1] is not None else -2, reverse=True)
                    for ((candidate, expected), score) in ranked:
                        if score is None or score < self._semantic.threshold:
                            continue
                        with self._lock:
                            cached = self._cache.semantic_hit(candidate, expected)
                            if cached is not None:
                                mark_cache_hit()
                                return {**deepcopy(cached), 'cache_hit': True,
                                        'cache_match_type': 'semantic', 'cache_similarity': score}
        try:
            response = self.question_service.answer(question)
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
            with self._lock:
                if generation == self._generation:
                    self._cache.put(key, deepcopy(response))
        return {**response, 'cache_hit': False}

    def cache_stats(self):
        with self._lock:
            return {**self._cache.stats(), 'semantic_enabled': self._semantic.enabled,
                    'semantic_threshold': self._semantic.threshold}

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
