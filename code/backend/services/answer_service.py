"""One bounded response cache shared by extractive QA and LLM answers."""

from copy import deepcopy
from threading import Lock

from services.question_answering import (
    NoAnswerFound, ServiceUnavailable, clear_retrieval_trace,
    get_retrieval_trace, mark_cache_hit, record_question_policy,
)
from utilities.cache_lfu import CacheLFU
from services.question_policy import QuestionPolicy
from services.semantic_cache import SemanticCacheConfig, compatible, cosine


class AnswerService:
    def __init__(self, question_service, fallback_service, *, question_policy=None, cache_capacity=10, semantic_config=None):
        self.question_service = question_service
        self.fallback_service = fallback_service
        self._policy = question_policy if question_policy is not None else QuestionPolicy()
        self._cache = CacheLFU(capacity=cache_capacity)
        self._lock = Lock()
        self._semantic = semantic_config or SemanticCacheConfig()

    def answer(self, question, category):
        clear_retrieval_trace()
        try:
            decision = self._policy.before_answer(question)
        except (OSError, ValueError) as error:
            raise ServiceUnavailable() from error
        if decision:
            record_question_policy(decision["reason"])
            return decision
        key = (category, question)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                mark_cache_hit()
                return {**deepcopy(cached), 'cache_hit': True, 'cache_match_type': 'exact'}
        if self._semantic.enabled:
            with self._lock:
                candidates = [(candidate, answer) for candidate, answer in self._cache.candidates(category)
                              if compatible(question, candidate[1])]
            if candidates:
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
        if cacheable:
            with self._lock:
                self._cache.put(key, deepcopy(response))
        return {**response, 'cache_hit': False}

    def cache_stats(self):
        with self._lock:
            return {**self._cache.stats(), 'semantic_enabled': self._semantic.enabled,
                    'semantic_threshold': self._semantic.threshold}
