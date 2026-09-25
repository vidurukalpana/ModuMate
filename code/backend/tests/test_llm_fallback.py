"""Provider and API contract tests without models or a live Ollama server."""

from io import BytesIO
import json
from urllib.error import HTTPError, URLError
import unittest
from unittest.mock import Mock

from app import create_app
from evaluation.run import classify_response, summarize
from evaluation.confidence_sweep import replay
from services.llm_fallback import FallbackConfig, FallbackError, LLMFallback, prepare_excerpts
from services.question_answering import NoAnswerFound, _passages

PASSAGES = [{'source': 'Files/UMA.txt', 'topic': 'UMA', 'text': 'All processors have equal memory access time.'}]


def response(result, **extra):
    return BytesIO(json.dumps({'done': True, 'message': {'content': json.dumps(result)}, **extra}).encode())


class FallbackTests(unittest.TestCase):
    def provider(self, transport):
        return LLMFallback(FallbackConfig('ollama', model='test-model', timeout=2), transport=transport)

    def test_question_context_schema_and_provenance(self):
        transport = Mock(return_value=response({'status': 'answer', 'definition': 'Equal access time.', 'explanation': '', 'example': '', 'source_ids': ['S1']}))
        result = self.provider(transport).respond('Explain UMA', 'MP', 'low_qa_score', PASSAGES)
        request = transport.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, 'http://localhost:11434/api/chat')
        self.assertFalse(payload['stream'])
        self.assertEqual(payload['model'], 'test-model')
        self.assertEqual(payload['format']['properties']['source_ids']['items']['enum'], ['S1'])
        self.assertEqual(payload['format']['properties']['source_ids']['maxItems'], 1)
        self.assertEqual(transport.call_args.kwargs['timeout'], 2)
        user = json.loads(payload['messages'][1]['content'])
        self.assertEqual(user['question'], 'Explain UMA')
        self.assertEqual(user['excerpts'][0]['text'], PASSAGES[0]['text'])
        self.assertEqual(result['sources'][0]['source'], 'Files/UMA.txt')
        self.assertFalse(result['simulated'])

    def test_answer_fields_are_joined_into_an_explanation(self):
        transport = Mock(return_value=response({
            'definition': 'UMA stands for Uniform Memory Access.',
            'explanation': 'All processors have equal memory access time.', 'example': ' ',
            'source_ids': ['S1'], 'status': 'answer',
        }))
        result = self.provider(transport).respond('What is UMA?', 'MP', 'low_qa_score', PASSAGES)
        self.assertEqual(result['answer'], 'UMA stands for Uniform Memory Access. All processors have equal memory access time.')

    def test_abstention_and_missing_evidence(self):
        for status, behavior in [('abstain', 'abstain')]:
            provider = self.provider(Mock(return_value=response({'status': status, 'definition': 'Need more information.', 'explanation': '', 'example': '', 'source_ids': []})))
            result = provider.respond('question', 'MP', 'low_qa_score', PASSAGES)
            self.assertEqual(classify_response(200, result), behavior)
        transport = Mock()
        result = self.provider(transport).respond('question', 'MP', 'invalid_retrieval_score', [])
        self.assertTrue(result['abstained'])
        transport.assert_not_called()

    def test_abstention_discards_considered_sources(self):
        for status in ('abstain',):
            transport = Mock(return_value=response({
                'status': status, 'definition': 'Insufficient evidence.', 'explanation': '', 'example': '', 'source_ids': ['S1'],
            }))
            result = self.provider(transport).respond('question', 'MP', 'low_qa_score', PASSAGES)
            self.assertEqual(classify_response(200, result), 'abstain')
            self.assertEqual(result['sources'], [])

    def test_simulator_never_contacts_provider(self):
        transport = Mock()
        result = LLMFallback(FallbackConfig(), transport=transport).respond('q', 'MP', 'low_qa_score', PASSAGES)
        self.assertTrue(result['simulated'])
        self.assertEqual(result['sources'], [])
        transport.assert_not_called()

    def test_invalid_provider_outputs(self):
        invalid = [
            {'status': 'answer', 'definition': 'answer', 'explanation': '', 'example': '', 'source_ids': []},
            {'status': 'answer', 'definition': 'answer', 'explanation': '', 'example': '', 'source_ids': ['invented']},
            {'status': 'answer', 'definition': '', 'explanation': '', 'example': '', 'source_ids': ['S1']},
            {'status': 'clarify', 'definition': 'question', 'explanation': '', 'example': '', 'source_ids': ['invented']},
            {'status': 'unknown', 'definition': 'x', 'explanation': '', 'example': '', 'source_ids': []},
            {'status': 'answer', 'definition': 'answer', 'explanation': 1, 'example': '', 'source_ids': ['S1']},
            {'status': 'answer', 'text': 'answer', 'source_ids': ['S1']},
            [],
        ]
        for result in invalid:
            with self.subTest(result=result), self.assertRaises(FallbackError) as caught:
                self.provider(Mock(return_value=response(result))).respond('q', 'MP', 'low_qa_score', PASSAGES)
            self.assertEqual(caught.exception.code, 'invalid_response')
        for raw in [b'not json', b'{}', b'x' * (1024 * 1024 + 1)]:
            with self.assertRaises(FallbackError):
                self.provider(Mock(return_value=BytesIO(raw))).respond('q', 'MP', 'low_qa_score', PASSAGES)
        with self.assertRaises(FallbackError):
            self.provider(Mock(return_value=response({}, done_reason='length'))).respond('q', 'MP', 'low_qa_score', PASSAGES)

    def test_network_failures_have_safe_codes(self):
        for error, code in [(TimeoutError('private'), 'timeout'),
                            (URLError('private'), 'provider_unavailable'),
                            (HTTPError('url', 404, 'private', {}, None), 'provider_unavailable')]:
            with self.assertRaises(FallbackError) as caught:
                self.provider(Mock(side_effect=error)).respond('q', 'MP', 'low_qa_score', PASSAGES)
            self.assertEqual(caught.exception.code, code)

    def test_config_and_context_limits(self):
        for kwargs in [dict(mode='unknown'), dict(mode='ollama'), dict(timeout=float('nan')),
                       dict(timeout=0), dict(base_url='file:///tmp/a'), dict(base_url='http://user:secret@host')]:
            with self.assertRaises(ValueError):
                FallbackConfig(**kwargs)
        excerpts = prepare_excerpts(PASSAGES * 3)
        self.assertEqual(len(excerpts), 1)
        excerpts = prepare_excerpts([dict(PASSAGES[0], text='a' * 20000)])
        self.assertEqual(len(excerpts[0]['text']), 12000)


class RoutingTests(unittest.TestCase):
    def test_api_passes_evidence_and_preserves_real_failures(self):
        qa = Mock()
        qa.answer.side_effect = NoAnswerFound('low_qa_score', PASSAGES)
        fallback = Mock()
        fallback.respond.return_value = {'answer': 'Grounded answer', 'source': 'llm_fallback'}
        app = create_app(qa, fallback)
        client = app.test_client()
        payload = {'question': 'question', 'category': 'MP'}
        self.assertEqual(client.post('/api', json=payload).json['source'], 'llm_fallback')
        fallback.respond.assert_called_with('question', 'MP', 'low_qa_score', PASSAGES)
        for code, status in [('timeout', 504), ('provider_unavailable', 503), ('invalid_response', 502)]:
            fallback.respond.side_effect = FallbackError(code)
            with self.assertLogs(app.logger, level='WARNING'):
                result = client.post('/api', json=payload)
            self.assertEqual(result.status_code, status)
            self.assertEqual(result.json['code'], code)
        fallback.reset_mock()
        qa.answer.side_effect = None
        qa.answer.return_value = {'answer': 'Local answer', 'source': 'local_qa', 'sources': []}
        self.assertEqual(client.post('/api', json=payload).json, {'answer': 'Local answer', 'cache_hit': False, 'source': 'local_qa', 'sources': []})
        fallback.respond.assert_not_called()

    def test_explanatory_questions_prefer_ollama_over_extracted_spans(self):
        extracted = {'answer': 'Uniform Memory Access', 'source': 'local_qa', 'sources': []}
        explained = {'answer': 'UMA stands for Uniform Memory Access. It means equal access time.',
                     'source': 'llm_fallback', 'sources': [{'id': 'S1'}]}

        def local_answer(question):
            _passages.set(tuple(PASSAGES))
            return dict(extracted)

        cases = [('What is UMA?', 'ollama', explained, None, explained['answer']),
                 ('Explain UMA', 'ollama', explained, None, explained['answer']),
                 ('What is UMA?', 'ollama', {**explained, 'abstained': True}, None, extracted['answer']),
                 ('What is UMA?', 'ollama', None, FallbackError('timeout'), extracted['answer']),
                 ('UMA access time?', 'ollama', explained, None, extracted['answer']),
                 ('What is UMA?', 'simulated', explained, None, extracted['answer'])]
        for question, mode, generated, error, expected in cases:
            with self.subTest(question=question, mode=mode, error=error):
                qa = Mock()
                qa.answer.side_effect = local_answer
                fallback = Mock()
                fallback.config = FallbackConfig(mode, model='test-model')
                fallback.respond.return_value = generated
                fallback.respond.side_effect = error
                result = create_app(qa, fallback).test_client().post(
                    '/api', json={'question': question, 'category': 'MP'}).json
                self.assertEqual(result['answer'], expected)
                if mode == 'ollama' and question != 'UMA access time?':
                    fallback.respond.assert_called_once_with(question, 'MP', 'explanation_requested', PASSAGES)
                else:
                    fallback.respond.assert_not_called()

    def test_metrics_keep_qa_and_llm_separate(self):
        common = dict(expected_behavior='answer', actual_behavior='answer', exact_match=1, token_f1=1, behavior_match=True)
        rows = [dict(common, response={'answer': 'QA'}), dict(common, response={'answer': 'LLM', 'source': 'llm_fallback'})]
        metrics = summarize(rows)
        self.assertEqual(metrics['local_answer_count'], 1)
        self.assertEqual(metrics['llm_answer_count'], 1)
        self.assertEqual(metrics['answer_exact_match'], 1)
        with self.assertRaises(ValueError):
            replay({'metadata': {'fallback_mode': 'ollama'}}, .5)
