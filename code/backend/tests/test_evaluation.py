"""Verify evaluation scoring and provenance without downloading models."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from app import create_app
from evaluation.run import classify_response, evaluate, load_cases, text_scores
from services.question_answering import NoAnswerFound, ServiceUnavailable


class EvaluationTests(unittest.TestCase):
    def test_cases_cover_every_course_text_file(self):
        dataset = load_cases()
        covered = {s['path'] for c in dataset['cases'] for s in c['sources']}
        root = Path(__file__).resolve().parents[1] / 'text_files'
        self.assertEqual(covered, {str(p.relative_to(root)) for p in (root / 'Files').glob('*.txt')})
        self.assertEqual({c['kind'] for c in dataset['cases']},
                         {'direct', 'paraphrase', 'comparison', 'ambiguous', 'unsupported'})

    def test_scoring_handles_variants_and_repeated_tokens(self):
        self.assertEqual(text_scores('The SHARED OS!', ['a shared OS'])['exact_match'], 1)
        self.assertEqual(text_scores('SMPs', ['Symmetric Multi-processors', 'SMPs'])['token_f1'], 1)
        self.assertAlmostEqual(text_scores('cache cache cache', ['cache memory'])['token_f1'], 0.4)
        self.assertEqual(text_scores('', ['answer'])['token_f1'], 0)
        self.assertEqual(text_scores('NUMA', ['UMA'])['token_f1'], 0)

    def test_abstention_and_failures_are_not_clarification(self):
        self.assertEqual(classify_response(422, {'error': 'No answer'}), 'abstain')
        self.assertEqual(classify_response(503, {'error': 'Unavailable'}), 'error')
        self.assertEqual(classify_response(200, {'answer': ''}), 'error')
        self.assertEqual(classify_response(200, {'needs_clarification': True, 'clarification': 'Which system?'}), 'clarify')

    def test_report_denominators_include_unanswered_answer_cases(self):
        dataset = load_cases()
        cases = [dataset['cases'][0], dataset['cases'][1], dataset['cases'][24], dataset['cases'][27]]
        service = Mock()
        service.answer.side_effect = [cases[0]['reference_answers'][0], NoAnswerFound(), NoAnswerFound(), NoAnswerFound()]
        report = evaluate({'cases': cases}, create_app(service).test_client())
        self.assertEqual(report['summary']['answer_exact_match'], 0.5)
        self.assertEqual(report['summary']['non_answer_behavior_accuracy'], 0.5)
        self.assertEqual(report['summary']['clarification_matches'], 0)
        self.assertEqual(report['summary']['operational_errors'], 0)

    def test_unavailable_service_is_not_successful_abstention(self):
        service = Mock()
        service.answer.side_effect = ServiceUnavailable()
        app = create_app(service)
        with self.assertLogs(app.logger, level='ERROR'):
            report = evaluate({'cases': [load_cases()['cases'][-1]]}, app.test_client())
        self.assertEqual(report['summary']['operational_errors'], 1)
        self.assertEqual(report['summary']['non_answer_behavior_accuracy'], 0)

    def test_invalid_provenance_and_duplicates_are_rejected(self):
        original = load_cases()
        for change in ['quote', 'path', 'duplicate']:
            dataset = deepcopy(original)
            if change == 'duplicate':
                dataset['cases'].append(dataset['cases'][0])
            else:
                dataset['cases'][0]['sources'][0][change] = ('invented quote' if change == 'quote' else '../app.py')
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'cases.json'
                path.write_text(json.dumps(dataset))
                with self.assertRaises(ValueError):
                    load_cases(path)


if __name__ == '__main__':
    unittest.main()
