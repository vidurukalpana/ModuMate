"""Regression tests; models are substituted so tests need no downloads."""

import json
import unittest
from contextlib import nullcontext
from unittest.mock import Mock

import numpy as np

from app import create_app
from services.question_answering import (
    DATA_DIRECTORY, NoAnswerFound, QuestionAnsweringService,
    ServiceUnavailable,
)
from utilities.cache_lfu import CacheLFU
from services.retrieval import PassageChunk, load_course


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.service.answer.return_value = {"answer": "A shared memory system", "source": "local_qa", "sources": []}
        self.app = create_app(self.service)
        self.client = self.app.test_client()

    def test_health_does_not_initialize_models(self):
        response = create_app().test_client().get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'')

    def test_valid_request_trims_question(self):
        response = self.client.post('/api', json={'question': '  What is UMA?  ', 'category': 'MP'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'answer': 'A shared memory system', 'cache_hit': False, 'source': 'local_qa', 'sources': []})
        self.service.answer.assert_called_once_with('What is UMA?')

    def test_invalid_payloads_do_not_reach_service(self):
        for payload in [None, [], 'text', {}, {'question': 1, 'category': 'MP'},
                        {'question': ' ', 'category': 'MP'},
                        {'question': 'x' * 2001, 'category': 'MP'},
                        {'question': 'test', 'category': 'other'}]:
            with self.subTest(payload=payload):
                response = self.client.post('/api', data=json.dumps(payload), content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json)
        self.service.answer.assert_not_called()

    def test_http_errors_are_json_and_preserve_headers(self):
        for response, status in [
            (self.client.post('/api', data='{', content_type='application/json'), 400),
            (self.client.post('/api', data='text'), 415),
            (self.client.post('/api', data='x' * 17000, content_type='application/json'), 413),
            (self.client.get('/missing'), 404),
            (self.client.get('/api'), 405),
        ]:
            self.assertEqual(response.status_code, status)
            self.assertIn('error', response.json)
        self.assertIn('POST', self.client.get('/api').headers['Allow'])

    def test_service_errors_have_safe_status_and_message(self):
        for error, status in [(NoAnswerFound(), 200), (ServiceUnavailable('secret'), 503),
                              (RuntimeError('secret'), 500)]:
            self.service.answer.side_effect = error
            with self.assertLogs(self.app.logger, level='ERROR') if status != 200 else nullcontext():
                response = self.client.post('/api', json={'question': 'test', 'category': 'MP'})
            self.assertEqual(response.status_code, status)
            self.assertNotIn('secret', response.get_data(as_text=True))


class CacheTests(unittest.TestCase):
    def test_lfu_eviction_and_exact_matching(self):
        cache = CacheLFU(2)
        cache.put('one', 'a')
        cache.put('two', 'b')
        self.assertEqual(cache.get('one'), 'a')
        cache.put('three', 'c')
        self.assertIsNone(cache.get('two'))
        self.assertIsNone(cache.get('ONE'))
        self.assertEqual(cache.get('one'), 'a')

    def test_tie_evicts_oldest_and_update_keeps_other_entries(self):
        cache = CacheLFU(2)
        cache.put('one', 'a')
        cache.put('two', 'b')
        cache.put('two', 'updated')
        cache.put('three', 'c')
        self.assertIsNone(cache.get('one'))
        self.assertEqual(cache.get('two'), 'updated')

    def test_rows_start_at_zero_and_replacement_takes_first_lowest_row(self):
        cache = CacheLFU(4)
        for question in ['q1', 'q2', 'q3', 'q4']:
            cache.put(('MP', question), question.upper())
        self.assertEqual([r['access_count'] for r in cache.rows()], [0, 0, 0, 0])
        cache.get(('MP', 'q1'))
        cache.get(('MP', 'q1'))
        cache.get(('MP', 'q3'))
        # Rows 1 and 3 tie at 0; the first of them (q2) is replaced in place.
        cache.put(('MP', 'q5'), 'Q5')
        self.assertEqual([(r['question'], r['access_count']) for r in cache.rows()],
                         [('q1', 2), ('q5', 0), ('q3', 1), ('q4', 0)])
        # The new row keeps count 0 and is again the first lowest row.
        cache.put(('MP', 'q6'), 'Q6')
        self.assertEqual([r['question'] for r in cache.rows()], ['q1', 'q6', 'q3', 'q4'])

    def test_no_time_based_expiration_by_default(self):
        now = [0.]
        cache = CacheLFU(1, clock=lambda: now[0])
        cache.put('q', 'a')
        now[0] = 10 ** 9
        self.assertEqual(cache.get('q'), 'a')
        self.assertEqual(cache.stats()['expirations'], 0)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = QuestionAnsweringService()
        self.service._model = Mock()
        self.service._embeddings = object()
        self.service._chunks = [PassageChunk('first.txt', 'First', 'first line\nsecond line answer', 0),
                                PassageChunk('second.txt', 'Second', 'another passage', 0)]
        self.service._owners = [0, 1]
        self.service._summary_embeddings = object()
        self.service._cos_sim = Mock(return_value=np.array([[0.8], [0.2]]))
        self.service._qa_model = Mock(return_value={'answer': ' answer ', 'score': 0.8})

    def test_full_passage_context(self):
        self.assertEqual(self.service.answer('question')['answer'], 'answer')
        self.service._qa_model.assert_called_once_with(
            question='question', context='first line\nsecond line answer', handle_impossible_answer=True)
        self.service._model.encode.assert_called_once()

    def test_low_similarity_does_not_generate_fake_answer(self):
        self.service._cos_sim.return_value = np.array([[0.1], [0.2]])
        with self.assertRaises(NoAnswerFound):
            self.service.answer('unrelated')
        self.service._qa_model.assert_not_called()

    def test_empty_answer_is_not_cached(self):
        self.service._qa_model.return_value = {'answer': ' ', 'score': 0.1}
        with self.assertRaises(NoAnswerFound):
            self.service.answer('question')

    def test_bundled_dataset_loads_complete_passages(self):
        records = load_course(DATA_DIRECTORY)
        passages = [record[3] for record in records]
        self.assertGreater(len(passages), 0)
        expected = (DATA_DIRECTORY / 'Files' / 'Multiprocessors_performance_of_processor_systems .txt').read_text().strip()
        self.assertEqual(passages[0], expected)
        self.assertIn('\n', passages[0])


if __name__ == '__main__':
    unittest.main()
