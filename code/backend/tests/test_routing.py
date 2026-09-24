"""HTTP routing boundaries and evaluation denominators."""

import unittest
from unittest.mock import Mock

import numpy as np

from app import create_app
from evaluation.run import summarize
from services.fallback import simulated_fallback
from services.question_answering import QuestionAnsweringService
from services.retrieval import build_chunks


class RoutingTests(unittest.TestCase):
    def request(self, retrieval=.5, answer='answer', score=.5):
        service = QuestionAnsweringService()
        service._model = Mock()
        service._chunks, service._owners = build_chunks([('Topic', 'summary', 'source.txt', 'the answer')])
        service._embeddings = object()
        service._summary_embeddings = object()
        service._cos_sim = Mock(return_value=np.array([retrieval]))
        service._qa_model = Mock(return_value={'answer': answer, 'score': score})
        app = create_app(service)
        response = app.test_client().post('/api', json={'question': 'q', 'category': 'MP'})
        return response, app

    def test_above_qa_boundary_returns_and_caches_local_answer(self):
        response, service = self.request(score=.501)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'answer': 'answer', 'cache_hit': False})
        self.assertEqual(service.extensions['answer_service']._cache.get(('MP', 'q'))['answer'], 'answer')

    def test_fallback_reasons_and_cache_exclusion(self):
        cases = [({'retrieval': .499}, 'low_retrieval_score'),
                 ({'score': .499}, 'low_qa_score'),
                 ({'score': .5}, 'low_qa_score'),
                 ({'answer': '', 'score': .99}, 'no_extracted_answer'),
                 ({'score': float('nan')}, 'invalid_qa_score'),
                 ({'answer': 'invented', 'score': .99}, 'answer_not_in_context')]
        for kwargs, reason in cases:
            with self.subTest(reason=reason):
                response, service = self.request(**kwargs)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json['fallback_reason'], reason)
                self.assertTrue(response.json['simulated'])
                self.assertIsNone(service.extensions['answer_service']._cache.get(('MP', 'q')))
                if reason == 'low_retrieval_score':
                    service.extensions['question_service']._qa_model.assert_not_called()

    def test_unknown_internal_reason_is_not_exposed(self):
        self.assertEqual(simulated_fallback('private error')['fallback_reason'], 'no_accepted_answer')


class RoutingMetricTests(unittest.TestCase):
    def test_local_quality_includes_unsupported_answers_in_denominator(self):
        rows = [
            dict(expected_behavior='answer', actual_behavior='answer', exact_match=1, token_f1=1, behavior_match=True),
            dict(expected_behavior='answer', actual_behavior='simulated_fallback', exact_match=0, token_f1=0, behavior_match=False),
            dict(expected_behavior='abstain', actual_behavior='answer', exact_match=None, token_f1=None, behavior_match=False),
        ]
        summary = summarize(rows)
        self.assertEqual(summary['local_answer_count'], 2)
        self.assertEqual(summary['local_answer_exact_match_rate'], .5)
        self.assertEqual(summary['answer_exact_match'], .5)
        self.assertAlmostEqual(summary['simulated_fallback_rate'], 1/3)

    def test_empty_denominators_are_null(self):
        summary = summarize([])
        self.assertIsNone(summary['local_answer_exact_match_rate'])
        self.assertIsNone(summary['simulated_fallback_rate'])
