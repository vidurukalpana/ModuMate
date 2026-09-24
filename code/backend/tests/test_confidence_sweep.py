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
        self.assertEqual(replay(report, .199)['answer_exact_match'], 1)
        self.assertEqual(replay(report, .2)['answer_return_rate'], 0)
        self.assertEqual(replay(report, .3)['answer_return_rate'], 0)
        self.assertEqual(report['results'][0]['actual_behavior'], 'answer')

    def test_policy_decisions_survive_qa_cutoff_replay(self):
        report = self.report()
        report['results'] = [{
            'expected_behavior': 'abstain', 'actual_behavior': 'abstain',
            'behavior_match': True, 'exact_match': None, 'token_f1': None,
            'response': {'source': 'question_policy', 'reason': 'ambiguous_question'},
        }]
        summary = replay(report, .9)
        self.assertEqual(summary['non_answer_behavior_accuracy'], 1)
        self.assertEqual(summary['policy_response_count'], 1)

    def test_replay_requires_complete_uncached_results(self):
        report = self.report()
        report['results'][0]['retrieval']['outcome'] = 'cache_hit'
        with self.assertRaises(ValueError):
            replay(report, .15)
        report['results'][0]['retrieval']['outcome'] = 'initialization_failed'
        with self.assertRaises(ValueError):
            replay(report, .15)
