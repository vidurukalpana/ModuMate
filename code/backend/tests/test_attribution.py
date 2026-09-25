"""Source provenance, excerpts, evaluation, and cache regressions."""

from io import BytesIO
import json
import unittest
from unittest.mock import Mock

import numpy as np

from app import create_app
from evaluation.run import attribution_scores
from services.attribution import source_reference
from services.llm_fallback import FallbackConfig, LLMFallback
from services.question_answering import QuestionAnsweringService
from services.retrieval import build_chunks


class AttributionTests(unittest.TestCase):
    def test_selected_local_context_and_cached_citations(self):
        qa = QuestionAnsweringService()
        qa._model = Mock()
        qa._chunks, qa._owners = build_chunks([
            ('First', 'summary', 'Files/first.txt', 'first answer'),
            ('Second', 'summary', 'Files/second.txt', 'second answer'),
        ])
        qa._embeddings = qa._summary_embeddings = object()
        qa._cos_sim = Mock(return_value=np.array([.9, .8]))
        qa._qa_model = Mock(side_effect=[
            {'answer': 'first answer', 'score': .5},
            {'answer': 'second answer', 'score': .8},
        ])
        app = create_app(qa)
        service = app.extensions['answer_service']
        first = service.answer('question', 'MP')
        self.assertEqual(first['source'], 'local_qa')
        self.assertFalse(first['cache_hit'])
        expected = [{'id': 'S1', 'source': 'Files/second.txt', 'topic': 'Second',
                     'chunk_index': 0, 'excerpt': 'second answer'}]
        self.assertEqual(first['sources'], expected)
        first['sources'][0]['excerpt'] = 'mutated'
        second = service.answer('question', 'MP')
        self.assertTrue(second['cache_hit'])
        self.assertEqual(second['sources'], expected)
        self.assertEqual(second['source'], 'local_qa')
        self.assertEqual(qa._qa_model.call_count, 2)

    def test_ollama_citations_use_exact_supplied_excerpt_and_deduplicate(self):
        passage = {'source': 'Files/course.txt', 'topic': 'Course', 'chunk_index': 7,
                   'text': 'x' * 15000}
        envelope = {'done': True, 'message': {'content': json.dumps({
            'status': 'answer', 'definition': 'Answer', 'explanation': '', 'example': '', 'source_ids': ['S1', 'S1'],
        })}}
        transport = Mock(return_value=BytesIO(json.dumps(envelope).encode()))
        provider = LLMFallback(FallbackConfig('ollama', model='test'), transport=transport)
        result = provider.respond('question', 'MP', 'low_qa_score', [passage])
        sent = json.loads(json.loads(transport.call_args.args[0].data)['messages'][1]['content'])
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['excerpt'], sent['excerpts'][0]['text'])
        self.assertEqual(len(result['sources'][0]['excerpt']), 12000)
        self.assertEqual(result['sources'][0]['chunk_index'], 7)

    def test_private_or_traversing_paths_are_rejected(self):
        for path in ['/Users/private/course.txt', '../course.txt', 'Files/../secret', 'C:\\course.txt']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                source_reference({'source': path, 'topic': 'topic', 'text': 'evidence'}, 'S1')

    def test_source_metrics_penalize_missing_and_extra_files(self):
        case = {'expected_behavior': 'answer', 'sources': [{'path': 'a'}, {'path': 'b'}]}
        body = {'sources': [{'source': 'a'}, {'source': 'a'}, {'source': 'wrong'}]}
        self.assertEqual(attribution_scores(case, body, 'answer'),
                         {'source_precision': .5, 'source_recall': .5})
        self.assertEqual(attribution_scores(case, {'sources': []}, 'answer'),
                         {'source_precision': 0, 'source_recall': 0})
        self.assertIsNone(attribution_scores(case, {}, 'abstain')['source_precision'])
