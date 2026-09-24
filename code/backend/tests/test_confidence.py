"""Acceptance boundaries, safe refusals, and cache behavior with confidence gates."""

import unittest
from unittest.mock import Mock
import numpy as np

from app import create_app
from services.confidence import ConfidencePolicy
from services.question_answering import QuestionAnsweringService, get_retrieval_trace
from services.retrieval import build_chunks


class PolicyTests(unittest.TestCase):
    def test_invalid_configuration(self):
        for value in (-.1, 1.1, float('nan'), float('inf'), True, '0.5'):
            for field in ('min_qa_score', 'min_retrieval_score'):
                with self.subTest(value=value, field=field), self.assertRaises(ValueError):
                    ConfidencePolicy(**{field: value})

    def test_boundaries_and_no_answer_score(self):
        policy = ConfidencePolicy()
        self.assertIsNone(policy.retrieval_rejection(.5))
        self.assertEqual(policy.retrieval_rejection(.499), 'below_retrieval_threshold')
        self.assertEqual(policy.answer_rejection('answer', .5, 'an answer'), 'below_qa_threshold')
        self.assertIsNone(policy.answer_rejection('answer', .501, 'an answer'))
        self.assertEqual(policy.answer_rejection('answer', .499, 'an answer'), 'below_qa_threshold')
        self.assertEqual(policy.answer_rejection('', .999, 'an answer'), 'qa_returned_no_answer')
        self.assertEqual(policy.answer_rejection('invented', .99, 'an answer'), 'answer_not_in_context')
        self.assertIsNone(policy.answer_rejection('an answer', .9, 'an\n answer'))
        for score in (float('nan'), float('inf'), -.1, 1.1):
            self.assertEqual(policy.answer_rejection('answer', score, 'answer'), 'invalid_qa_score')


class ServiceConfidenceTests(unittest.TestCase):
    def setUp(self):
        self.service = QuestionAnsweringService()
        self.service._model = Mock()
        self.service._chunks, self.service._owners = build_chunks([
            ('one', 'summary', 'one.txt', 'first answer'),
            ('two', 'summary', 'two.txt', 'second answer'),
        ])
        self.service._embeddings = object()
        self.service._summary_embeddings = object()
        self.service._cos_sim = Mock(return_value=np.array([.8, .7]))
        self.service._qa_model = Mock()
        app = create_app(self.service)
        self.cache = app.extensions["answer_service"]._cache
        self.client = app.test_client()

    def ask(self):
        return self.client.post('/api', json={'question': 'question', 'category': 'MP'})

    def test_rejected_answers_use_simulated_fallback_and_are_never_cached(self):
        self.service._qa_model.side_effect = [
            {'answer': 'first answer', 'score': .1},
            {'answer': 'second answer', 'score': .14},
        ]
        self.assertEqual(self.ask().json['source'], 'simulated_fallback')
        self.assertIsNone(self.cache.get(('MP', 'question')))
        trace = get_retrieval_trace()
        self.assertEqual(trace['outcome'], 'no_candidate_passed_confidence')
        self.assertTrue(all(c['rejection_reason'] == 'below_qa_threshold' for c in trace['candidates']))
        self.service._qa_model.side_effect = None
        self.service._qa_model.return_value = {'answer': 'first answer', 'score': .8}
        self.assertEqual(self.ask().json['answer'], 'first answer')
        self.assertEqual(self.cache.get(('MP', 'question'))['answer'], 'first answer')

    def test_rejected_high_score_does_not_hide_valid_second_candidate(self):
        self.service._qa_model.side_effect = [
            {'answer': 'not in the source', 'score': .99},
            {'answer': 'second answer', 'score': .6},
        ]
        self.assertEqual(self.ask().json['answer'], 'second answer')
        self.assertEqual(get_retrieval_trace()['candidates'][0]['rejection_reason'], 'answer_not_in_context')

    def test_invalid_numeric_scores_fail_closed(self):
        self.service._qa_model.return_value = {'answer': 'first answer', 'score': float('nan')}
        self.assertEqual(self.ask().json['source'], 'simulated_fallback')
        self.assertIsNone(get_retrieval_trace()['candidates'][0]['qa_score'])
        self.service._cos_sim.return_value = np.array([float('nan'), .8])
        self.assertEqual(self.ask().json['source'], 'simulated_fallback')
        self.assertEqual(get_retrieval_trace()['outcome'], 'invalid_retrieval_score')

    def test_custom_policy_changes_acceptance(self):
        service = QuestionAnsweringService(confidence_policy=ConfidencePolicy(.6, .8))
        self.assertEqual(service.confidence_policy.min_qa_score, .8)
        with self.assertRaises(AttributeError):
            service.confidence_policy = ConfidencePolicy()
