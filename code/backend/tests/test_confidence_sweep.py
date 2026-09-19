"""Replay cutoffs without turning empty answers or errors into successes."""

import unittest

from evaluation.confidence_sweep import replay


class SweepTests(unittest.TestCase):
    def report(self):
        return {'results': [{
            'expected_behavior': 'answer', 'actual_behavior': 'answer',
            'reference_answers': ['correct'], 'exact_match': 1, 'token_f1': 1,
            'retrieval': {'outcome': 'answered', 'candidates': [
                {'eligible': True, 'answer': '', 'qa_score': .99},
                {'eligible': True, 'answer': 'wrong', 'qa_score': .9,
                 'rejection_reason': 'answer_not_in_context'},
                {'eligible': True, 'answer': 'correct', 'qa_score': .2},
            ]},
        }]}

    def test_replay_retains_non_score_rejections(self):
        report = self.report()
        self.assertEqual(replay(report, .2)['answer_exact_match'], 1)
        self.assertEqual(replay(report, .3)['answer_return_rate'], 0)
        self.assertEqual(report['results'][0]['actual_behavior'], 'answer')

    def test_replay_requires_complete_uncached_results(self):
        report = self.report()
        report['results'][0]['retrieval']['outcome'] = 'cache_hit'
        with self.assertRaises(ValueError):
            replay(report, .15)
        report['results'][0]['retrieval']['outcome'] = 'initialization_failed'
        with self.assertRaises(ValueError):
            replay(report, .15)
