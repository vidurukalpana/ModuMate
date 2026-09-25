"""Request tracing, bounded collection, readiness and sensitive-data exclusion."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import unittest
from unittest.mock import Mock

from app import create_app
from services.llm_fallback import FallbackConfig, LLMFallback
from services.observability import Metrics
from services.question_answering import QuestionAnsweringService, NoAnswerFound


class ObservabilityTests(unittest.TestCase):
    def test_request_id_privacy_errors_and_metrics_auth(self):
        qa = Mock()
        qa.answer.side_effect = RuntimeError('SECRET internal path')
        app = create_app(qa, Mock(), metrics_token='SECRET')
        client = app.test_client()
        with self.assertLogs(app.logger, level='INFO') as logs:
            response = client.post('/api', json={'question': 'private question', 'category': 'MP'},
                                   headers={'X-Request-ID': 'SECRET incoming', 'Authorization': 'Bearer SECRET'})
        self.assertEqual(response.status_code, 500)
        event = json.loads(logs.records[-1].getMessage())
        self.assertEqual(event['request_id'], response.headers['X-Request-ID'])
        self.assertEqual(len(event['request_id']), 32)
        self.assertEqual(event['error_category'], 'unexpected_error')
        self.assertNotIn('SECRET', str(logs.output))
        self.assertNotIn('private question', str(logs.output))
        self.assertEqual(client.get('/metrics').status_code, 401)
        metrics = client.get('/metrics', headers={'Authorization': 'Bearer SECRET'})
        self.assertEqual(metrics.status_code, 200)
        self.assertNotIn('SECRET', metrics.get_data(as_text=True))
        self.assertEqual(metrics.json['counters']['error_category:unexpected_error'], 1)
        self.assertEqual(metrics.headers['Cache-Control'], 'no-store')
        self.assertEqual(create_app(Mock(), Mock(), metrics_token='').test_client().get('/metrics').status_code, 403)
        with self.assertLogs(app.logger, level='INFO') as missing_logs:
            missing = client.get('/SECRET-path?token=SECRET')
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn('SECRET', str(missing_logs.output))
        self.assertNotEqual(missing.headers['X-Request-ID'], response.headers['X-Request-ID'])

    def test_readiness_is_a_snapshot_and_never_loads_models(self):
        qa = QuestionAnsweringService()
        qa._initialize = Mock()
        app = create_app(qa, Mock())
        client = app.test_client()
        self.assertEqual(client.get('/health').status_code, 200)
        self.assertEqual(client.get('/ready').status_code, 503)
        qa._model = Mock()
        self.assertEqual(client.get('/ready').status_code, 200)
        self.assertEqual(client.get('/ready').json['ollama'], 'not_checked')
        qa.reset()
        self.assertEqual(client.get('/ready').status_code, 503)
        qa._initialize.assert_not_called()

    def test_provider_calls_are_not_cached_origin_counts(self):
        qa = Mock()
        qa.answer.side_effect = NoAnswerFound('low_qa_score', [
            {'source': 'Files/course.txt', 'topic': 'Course', 'text': 'Evidence'}])
        payload = {'done': True, 'message': {'content': json.dumps(
            {'status': 'answer', 'definition': 'Evidence', 'explanation': '', 'example': '', 'source_ids': ['S1']})}}
        transport = Mock(return_value=BytesIO(json.dumps(payload).encode()))
        fallback = LLMFallback(FallbackConfig('ollama', model='test'), transport=transport)
        app = create_app(qa, fallback)
        client = app.test_client()
        for _ in range(2):
            self.assertEqual(client.post('/api', json={'question': 'question', 'category': 'MP'}).status_code, 200)
        metrics = app.extensions['metrics'].snapshot()
        self.assertEqual(metrics['counters']['provider_calls'], 1)
        self.assertEqual(metrics['counters']['source:llm_fallback'], 2)
        self.assertEqual(metrics['counters']['cache_match_type:exact'], 1)
        self.assertEqual(metrics['timings']['ollama_http']['count'], 1)
        self.assertEqual(metrics['timings']['cache_lookup']['count'], 2)

    def test_provider_timeout_keeps_stage_timing(self):
        qa = Mock()
        qa.answer.side_effect = NoAnswerFound('low_qa_score', [
            {'source': 'Files/course.txt', 'topic': 'Course', 'text': 'Evidence'}])
        fallback = LLMFallback(FallbackConfig('ollama', model='test'), transport=Mock(side_effect=TimeoutError('SECRET')))
        app = create_app(qa, fallback)
        with self.assertLogs(app.logger, level='ERROR') as logs:
            response = app.test_client().post('/api', json={'question': 'question', 'category': 'MP'})
        self.assertEqual(response.status_code, 504)
        event = json.loads(logs.records[-1].getMessage())
        self.assertEqual(event['error_category'], 'timeout')
        self.assertEqual(event['provider_calls'], 1)
        self.assertIn('ollama_http', event['stages'])
        self.assertNotIn('SECRET', str(logs.output))
        self.assertNotIn('private question', str(logs.output))

    def test_bounded_samples_and_thread_safe_counters(self):
        metrics = Metrics(sample_limit=8)
        event = {'status': 200, 'provider_calls': 0, 'duration_seconds': .2, 'stages': {'retrieval': .1}}
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: metrics.record(event), range(100)))
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot['counters']['requests'], 100)
        self.assertEqual(snapshot['timings']['retrieval']['count'], 100)
        self.assertEqual(snapshot['timings']['retrieval']['recent_sample_count'], 8)
        self.assertAlmostEqual(snapshot['timings']['request']['recent_p95_seconds'], .2)
        snapshot['counters']['requests'] = 0
        self.assertEqual(metrics.snapshot()['counters']['requests'], 100)
