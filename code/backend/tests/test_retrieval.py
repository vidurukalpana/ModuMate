"""Chunk coverage, candidate selection, and retrieval failure diagnostics."""

import unittest
from unittest.mock import Mock
import numpy as np

from services.retrieval import CONTEXT_WORDS, PassageChunk, build_chunks, split_passage
from services.question_answering import NoAnswerFound, QuestionAnsweringService, get_retrieval_trace


class ChunkTests(unittest.TestCase):
    def test_long_source_context_is_bounded_and_contains_the_search_chunk(self):
        text = ' '.join(f'word{i}' for i in range(500))
        chunks, _ = build_chunks([('Topic', 'Summary', 'Files/source.txt', text)])
        for chunk in chunks:
            self.assertLessEqual(len(chunk.context.split()), CONTEXT_WORDS)
            self.assertIn(chunk.text, chunk.context)

    def test_long_paragraph_windows_overlap_without_losing_words(self):
        words = [str(i) for i in range(205)]
        chunks = list(split_passage(' '.join(words)))
        self.assertTrue(all(len(c.split()) <= 80 for c in chunks))
        self.assertEqual(chunks[0].split()[-20:], chunks[1].split()[:20])
        self.assertEqual(set(' '.join(chunks).split()), set(words))

    def test_paragraphs_and_provenance_are_preserved(self):
        chunks, owners = build_chunks([('Topic', 'Summary', 'Files/source.txt', 'First paragraph.\n\nSecond paragraph.')])
        self.assertEqual([c.text for c in chunks], ['First paragraph.', 'Second paragraph.'])
        self.assertEqual(chunks[0].context, 'First paragraph.\n\nSecond paragraph.')
        self.assertEqual(owners, [0, 0])
        self.assertEqual(chunks[0].source, 'Files/source.txt')
        self.assertEqual(chunks[0].index, 0)
        self.assertEqual(list(split_passage('  ')), [])
        with self.assertRaises(ValueError):
            list(split_passage('text', 20, 20))


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.service = QuestionAnsweringService()
        self.service._model = Mock()
        self.service._chunks, self.service._owners = build_chunks([
            (str(i), 'summary', f'Files/{i}.txt', f'Passage number {i}') for i in range(4)
        ])
        self.service._embeddings = object()
        self.service._summary_embeddings = object()
        self.service._cos_sim = Mock(side_effect=[np.array([.9, .8, .7, .6]), np.array([.1] * 4)])
        self.service._qa_model = Mock(side_effect=[
            {'answer': '', 'score': .9}, {'answer': 'second', 'score': .7},
            {'answer': 'third', 'score': .4},
        ])

    def test_second_candidate_can_answer_when_first_cannot(self):
        self.assertEqual(self.service.answer('question'), 'second')
        self.assertEqual(self.service._qa_model.call_count, 3)
        trace = get_retrieval_trace()
        self.assertEqual(trace['selected']['source'], 'Files/1.txt')
        self.assertEqual(trace['outcome'], 'answered')
        self.assertEqual(self.service.answer('question'), 'second')
        self.assertEqual(get_retrieval_trace()['outcome'], 'cache_hit')
        self.assertEqual(get_retrieval_trace()['candidates'], [])

    def test_shared_context_is_evaluated_only_once(self):
        self.service._chunks = [
            PassageChunk(f'Files/{i}.txt', 'Topic', f'chunk {i}', i, 'shared context')
            for i in range(4)
        ]
        self.service._qa_model.side_effect = [{'answer': 'answer', 'score': .8}]
        self.assertEqual(self.service.answer('question'), 'answer')
        self.service._qa_model.assert_called_once_with(
            question='question', context='shared context', handle_impossible_answer=True)

    def test_low_similarity_does_not_run_qa(self):
        self.service._cos_sim.side_effect = [np.array([.1] * 4), np.array([.2] * 4)]
        with self.assertRaises(NoAnswerFound):
            self.service.answer('unrelated')
        self.service._qa_model.assert_not_called()
        self.assertEqual(get_retrieval_trace()['outcome'], 'below_retrieval_threshold')

    def test_summary_can_retrieve_a_chunk_and_empty_qa_has_distinct_reason(self):
        self.service._cos_sim.side_effect = [np.array([.1] * 4), np.array([.8, .1, .1, .1])]
        self.service._qa_model.side_effect = [{'answer': '', 'score': .9}]
        with self.assertRaises(NoAnswerFound):
            self.service.answer('question')
        self.service._qa_model.assert_called_once()
        self.assertEqual(get_retrieval_trace()['outcome'], 'qa_returned_no_answer')

    def test_duplicate_chunks_do_not_use_candidate_slots(self):
        self.service._chunks, self.service._owners = build_chunks([
            ('Topic', 'summary', f'Files/{i}.txt', text)
            for i, text in enumerate(['same text', 'same text', 'another text', 'third text'])
        ])
        self.service.answer('question')
        self.assertEqual(len(get_retrieval_trace()['candidates']), 3)
        self.assertEqual([c['source'] for c in get_retrieval_trace()['candidates']],
                         ['Files/0.txt', 'Files/2.txt', 'Files/3.txt'])
