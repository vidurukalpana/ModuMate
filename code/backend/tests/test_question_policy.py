"""Unsupported/ambiguous routing and false-positive regression checks."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import create_app
from services.question_answering import NoAnswerFound, get_retrieval_trace
from services.question_policy import MIN_COURSE_RELEVANCE, QuestionPolicy


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = QuestionPolicy()

    def test_missing_subjects_return_standalone_limitations(self):
        for question in ['Which one is faster?', 'How many cycles does it take?',
                         'Explain that protocol.', 'Compare the two', 'How does it work?']:
            with self.subTest(question=question):
                result = self.policy.before_answer(question)
                self.assertTrue(result['abstained'])
                self.assertEqual(result['sources'], [])
                self.assertNotIn('?', result['answer'])
                self.assertEqual(result['reason'], 'ambiguous_question')
                self.assertFalse(result['cache_hit'])
                self.assertTrue(result['suggested_topics'])

    def test_named_supported_questions_remain_eligible(self):
        for question in ['What does SISD stand for?', 'What is CC-NUMA?',
                         'PLEASE explain UMA.', 'HOW DOES UMA WORK?',
                         'Compare UMA and NUMA.', 'Why does cache coherence matter?',
                         'How many cycles does a remote NC-NUMA access take?',
                         'Explain two ways of improving processor performance.',
                         'What does SIMD mean in a processor architecture?']:
            with self.subTest(question=question):
                self.assertIsNone(self.policy.before_answer(question))

    def test_missing_named_entities_abstain(self):
        for question in ['List the stages in a MIPS processor.',
                         'What is the L3 cache size of an Intel Core i9-14900K?',
                         'How does a risc-v processor work?']:
            with self.subTest(question=question):
                result = self.policy.before_answer(question)
                self.assertTrue(result['abstained'])
                self.assertEqual(result['sources'], [])
                self.assertEqual(result['reason'], 'missing_course_material')

    def test_vocabulary_comes_from_supplied_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'topic.txt').write_text('XYZ is the documented architecture.')
            policy = QuestionPolicy(path)
            self.assertIsNone(policy.before_answer('What is XYZ?'))
            self.assertTrue(policy.before_answer('What is ABC?')['abstained'])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                QuestionPolicy(directory).before_answer('What is ABC?')

    def test_relevance_guard_is_separate_from_qa_threshold(self):
        for score, abstain in [(.19, True), (MIN_COURSE_RELEVANCE, False), (.49, False)]:
            result = self.policy.after_retrieval('low_retrieval_score', {'candidates': [{'retrieval_score': score}]})
            self.assertEqual(result is not None, abstain)
        self.assertIsNone(self.policy.after_retrieval('no_extracted_answer', {'candidates': [{'retrieval_score': .1}]}))
        self.assertIsNone(self.policy.after_retrieval('low_retrieval_score', {'candidates': [{'retrieval_score': float('nan')}]}))
        self.assertIsNone(self.policy.after_retrieval('low_retrieval_score', None))


class PolicyRoutingTests(unittest.TestCase):
    def setUp(self):
        self.qa, self.fallback = Mock(), Mock()
        self.app = create_app(self.qa, self.fallback)
        self.client = self.app.test_client()

    def ask(self, question, category='MP'):
        return self.client.post('/api', json={'question': question, 'category': category})

    def test_policy_responses_bypass_models_and_cache(self):
        for question in ['Explain that protocol.', 'Describe the MIPS pipeline.']:
            for _ in range(2):
                result = self.ask(question)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json['source'], 'question_policy')
                self.assertFalse(result.json['cache_hit'])
                self.assertEqual(get_retrieval_trace()['policy_reason'], result.json['reason'])
        self.qa.answer.assert_not_called()
        self.fallback.respond.assert_not_called()
        self.assertEqual(len(self.app.extensions['answer_service']._cache._entries), 0)

    def test_unrelated_question_does_not_call_fallback(self):
        self.qa.answer.side_effect = NoAnswerFound('low_retrieval_score', [{'text': 'course'}])
        trace = {'outcome': 'below_retrieval_threshold', 'candidates': [{'retrieval_score': .1}]}
        with patch('services.answer_service.get_retrieval_trace', return_value=trace):
            result = self.ask('How do I bake bread?')
        self.assertTrue(result.json['abstained'])
        self.assertEqual(result.json['reason'], 'insufficient_course_relevance')
        self.fallback.respond.assert_not_called()

    def test_borderline_course_question_still_calls_fallback(self):
        self.qa.answer.side_effect = NoAnswerFound('low_retrieval_score', [{'text': 'SISD passage'}])
        self.fallback.respond.return_value = {'answer': 'simulator', 'simulated': True}
        with patch('services.answer_service.get_retrieval_trace', return_value={'candidates': [{'retrieval_score': .49}]}):
            result = self.ask('What does SISD stand for?')
        self.assertEqual(result.json['answer'], 'simulator')
        self.fallback.respond.assert_called_once()

    def test_invalid_requests_still_return_400(self):
        self.assertEqual(self.ask('What is UMA?', category='other').status_code, 400)
        self.assertEqual(self.ask(' ').status_code, 400)
        self.qa.answer.assert_not_called()

    def test_unreadable_course_is_service_failure_not_refusal(self):
        self.app.extensions['answer_service']._policy = Mock()
        self.app.extensions['answer_service']._policy.before_answer.side_effect = OSError('private path')
        with self.assertLogs(self.app.logger, level='ERROR'):
            result = self.ask('What is UMA?')
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('private path', str(result.json))
