"""The API shares four rows across local and generated answers."""

from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock

from app import create_app
from services.answer_service import AnswerService
from services.llm_fallback import FallbackError
from services.question_answering import NoAnswerFound, get_retrieval_trace


def generated():
    return {'answer': 'SISD expansion', 'source': 'llm_fallback', 'provider': 'ollama',
            'model': 'llama3.2:1b', 'simulated': False,
            'sources': [{'id': 'S1', 'source': 'course.txt', 'topic': 'Flynn',
                         'chunk_index': 0, 'excerpt': 'SISD expansion from notes.'}]}


class SharedCacheTests(unittest.TestCase):
    def setUp(self):
        self.qa = Mock()
        self.qa.answer.side_effect = NoAnswerFound()
        self.llm = Mock()
        self.llm.respond.return_value = generated()
        self.app = create_app(self.qa, self.llm, cache_capacity=4)
        self.service = self.app.extensions['answer_service']

    def test_repeat_llm_question_bypasses_both_models_and_keeps_provenance(self):
        client = self.app.test_client()
        first = client.post('/api', json={'question': '  q  ', 'category': 'MP'}).json
        second = client.post('/api', json={'question': 'q', 'category': 'MP'}).json
        self.assertFalse(first['cache_hit'])
        self.assertTrue(second['cache_hit'])
        self.assertEqual(second['source'], 'llm_fallback')
        self.assertEqual(second['sources'], first['sources'])
        self.qa.answer.assert_called_once()
        self.llm.respond.assert_called_once()
        self.assertEqual(get_retrieval_trace()['outcome'], 'cache_hit')

    def test_cache_is_four_total_entries_with_lfu_eviction(self):
        self.assertEqual(self.service.cache_stats()['capacity'], 4)
        self.service.answer('llm-0', 'MP')
        self.service.answer('llm-0', 'MP')
        self.qa.answer.side_effect = None
        self.qa.answer.return_value = {'answer': 'QA answer', 'source': 'local_qa', 'sources': []}
        for i in range(4):
            self.service.answer(f'qa-{i}', 'MP')
        self.assertEqual(len(self.service._cache._entries), 4)
        self.assertTrue(self.service.answer('llm-0', 'MP')['cache_hit'])
        # qa-0..qa-2 filled rows 1-3 at count 0; qa-3 replaced the first of them.
        self.assertTrue(self.service.answer('qa-3', 'MP')['cache_hit'])
        self.assertTrue(self.service.answer('qa-2', 'MP')['cache_hit'])
        self.assertFalse(self.service.answer('qa-0', 'MP')['cache_hit'])

    def test_non_answers_and_errors_are_not_cached(self):
        for response in [dict(generated(), simulated=True), dict(generated(), abstained=True),
                         dict(generated(), sources=[])]:
            self.llm.respond.return_value = response
            self.assertFalse(self.service.answer('q', 'MP')['cache_hit'])
            self.assertIsNone(self.service._cache.get(('MP', 'q')))
        self.llm.respond.side_effect = FallbackError('timeout')
        with self.assertRaises(FallbackError):
            self.service.answer('q', 'MP')
        self.assertIsNone(self.service._cache.get(('MP', 'q')))

    def test_response_mutation_does_not_change_cache_and_categories_are_separate(self):
        result = self.service.answer('q', 'MP')
        result['sources'][0]['topic'] = 'mutated'
        cached = self.service.answer('q', 'MP')
        self.assertEqual(cached['sources'][0]['topic'], 'Flynn')
        cached['sources'].clear()
        self.assertTrue(self.service.answer('q', 'MP')['sources'])
        # Restore mock output mutated through first response before next uncached call.
        self.llm.respond.return_value = generated()
        self.assertFalse(self.service.answer('q', 'another-category')['cache_hit'])

    def test_parallel_cache_hits_are_safe(self):
        self.service.answer('q', 'MP')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.service.answer('q', 'MP'), range(20)))
        self.assertTrue(all(r['cache_hit'] for r in results))
        self.llm.respond.assert_called_once()
