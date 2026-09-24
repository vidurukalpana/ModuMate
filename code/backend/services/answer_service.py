"""One bounded response cache shared by extractive QA and LLM answers."""

from copy import deepcopy
from threading import Lock

from services.question_answering import NoAnswerFound, mark_cache_hit
from utilities.cache_lfu import CacheLFU


class AnswerService:
    def __init__(self, question_service, fallback_service):
        self.question_service = question_service
        self.fallback_service = fallback_service
        self._cache = CacheLFU(capacity=10)
        self._lock = Lock()

    def answer(self, question, category):
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
            response = self.fallback_service.respond(question, category, error.reason, error.passages)
            cacheable = (
                response.get('source') == 'llm_fallback'
                and response.get('simulated') is False
                and bool(response.get('sources'))
                and isinstance(response.get('answer'), str) and bool(response['answer'].strip())
                and not response.get('abstained') and not response.get('needs_clarification')
            )
        if cacheable:
            with self._lock:
                self._cache.put(key, deepcopy(response))
        return {**response, 'cache_hit': False}
