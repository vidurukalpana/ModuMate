"""One bounded response cache shared by extractive QA and LLM answers."""

from copy import deepcopy
from threading import Lock

from services.question_answering import (
    NoAnswerFound, ServiceUnavailable, clear_retrieval_trace,
    get_retrieval_trace, mark_cache_hit, record_question_policy,
)
from utilities.cache_lfu import CacheLFU
from services.question_policy import QuestionPolicy


class AnswerService:
    def __init__(self, question_service, fallback_service, *, question_policy=None):
        self.question_service = question_service
        self.fallback_service = fallback_service
        self._policy = question_policy if question_policy is not None else QuestionPolicy()
        self._cache = CacheLFU(capacity=10)
        self._lock = Lock()

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
                return {**deepcopy(cached), 'cache_hit': True}
        try:
            response = {'answer': self.question_service.answer(question)}
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
