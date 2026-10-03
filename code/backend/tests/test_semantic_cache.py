"""Semantic hits must preserve evidence and never cross key-term/category boundaries."""

import os
import unittest
from unittest.mock import Mock, patch

from services.answer_service import AnswerService
from services.semantic_cache import SemanticCacheConfig, compatible, cosine


class SemanticTests(unittest.TestCase):
    def service(self, enabled=True, capacity=1, vectors=None):
        qa = Mock()
        qa.answer.return_value = {'answer': 'expansion', 'source': 'local_qa',
                                  'sources': [{'source': 'Files/course.txt', 'excerpt': 'evidence'}]}
        vectors = vectors if vectors is not None else {}
        qa.encode_questions.side_effect = lambda questions: [vectors.get(q, [1., 0.]) for q in questions]
        policy = Mock(before_answer=Mock(return_value=None), after_retrieval=Mock(return_value=None))
        return AnswerService(qa, Mock(), question_policy=policy, cache_capacity=capacity,
                             semantic_config=SemanticCacheConfig(enabled, .75)), qa

    def test_hit_preserves_citations_without_new_entry_or_qa(self):
        service, qa = self.service()
        service.answer('What does SISD stand for?', 'MP')
        result = service.answer('What is the full form of SISD?', 'MP')
        self.assertEqual(result['cache_match_type'], 'semantic')
        self.assertEqual(result['cache_similarity'], 1.)
        self.assertEqual(result['cache_matched_question'], 'What does SISD stand for?')
        self.assertEqual(result['source'], 'local_qa')
        self.assertEqual(result['sources'][0]['excerpt'], 'evidence')
        qa.answer.assert_called_once()
        self.assertEqual(service.cache_stats()['semantic_hits'], 1)
        self.assertEqual(service.cache_stats()['misses'], 1)
        self.assertEqual(service.cache_stats()['entries'], 1)
        self.assertEqual(service.cache_rows()[0]['access_count'], 1)
        # Stored embeddings are reused: one encode on insert, one for the paraphrase.
        self.assertEqual(qa.encode_questions.call_count, 2)
        service.answer('What does SISD stand for?', 'MP')
        self.assertEqual(qa.encode_questions.call_count, 2)
        self.assertEqual(service.cache_stats()['exact_hits'], 1)

    def test_plain_paraphrase_hits_above_threshold(self):
        service, _ = self.service()
        service.answer('What is cache coherence?', 'MP')
        self.assertEqual(service.answer('Explain cache coherence.', 'MP')['cache_match_type'], 'semantic')

    def test_highest_similarity_wins(self):
        vectors = {'What is bus snooping?': [1., 0.], 'What is a snoop bus?': [.6, .8],
                   'How does bus snooping work?': [.96, .28]}
        service, qa = self.service(capacity=4, vectors=vectors)
        qa.answer.side_effect = lambda q: {'answer': q, 'source': 'local_qa', 'sources': [{'excerpt': 'e'}]}
        service.answer('What is a snoop bus?', 'MP')
        service.answer('What is bus snooping?', 'MP')
        self.assertEqual(service.cache_stats()['entries'], 2)
        # Similarities: 0.96 to bus snooping and 0.80 to snoop bus; both pass 0.75.
        result = service.answer('How does bus snooping work?', 'MP')
        self.assertEqual(result['answer'], 'What is bus snooping?')

    def test_similarity_must_be_strictly_greater_than_threshold(self):
        for vector, hit in [([.75, (1 - .75 ** 2) ** .5], False), ([.76, (1 - .76 ** 2) ** .5], True)]:
            with self.subTest(similarity=vector[0]):
                service, _ = self.service(vectors={'Explain cache coherence.': vector})
                service.answer('What is cache coherence?', 'MP')
                self.assertEqual(service.answer('Explain cache coherence.', 'MP')['cache_hit'], hit)

    def test_disabled_and_category_mismatch_skip_encoder(self):
        for enabled, category in [(False, 'MP'), (True, 'other')]:
            service, qa = self.service(enabled)
            service.answer('What does SISD stand for?', 'MP')
            qa.encode_questions.reset_mock()
            self.assertFalse(service.answer('What is the full form of SISD?', category)['cache_hit'])
            if enabled:
                # Only the new answer's own embedding is computed for storage.
                self.assertEqual(qa.encode_questions.call_count, 1)
            else:
                qa.encode_questions.assert_not_called()

    def test_low_similarity_and_invalid_vectors_miss(self):
        for vector in [[0., 1.], [float('nan'), 0.], [0., 0.]]:
            service, _ = self.service(vectors={'What is the full form of SISD?': vector})
            service.answer('What does SISD stand for?', 'MP')
            self.assertFalse(service.answer('What is the full form of SISD?', 'MP')['cache_hit'])
            self.assertEqual(service.cache_stats()['misses'], 2)

    def test_evicted_snapshot_cannot_return_stale_answer(self):
        service, qa = self.service()
        service.answer('What does SISD stand for?', 'MP')

        def encode(_):
            with service._lock:
                service._cache.put(('MP', 'replacement'), {'answer': 'replacement'})
            return [[1., 0.]]
        qa.encode_questions.side_effect = encode
        self.assertFalse(service.answer('What is the full form of SISD?', 'MP')['cache_hit'])
        self.assertEqual(service.cache_stats()['semantic_hits'], 0)

    def test_different_key_terms_are_blocked(self):
        for left, right in [
            ('What is UMA?', 'What is NUMA?'),
            ('What is NC-NUMA?', 'What is CC-NUMA?'),
            ('What does SISD stand for?', 'What does SIMD stand for?'),
            ('What is an L1 cache?', 'What is an L2 cache?'),
            ('What is write-invalidate?', 'What is write-update?'),
            ('What are the advantages of UMA?', 'What are the disadvantages of UMA?'),
            ('What is cache coherence?', 'What is not cache coherence?'),
        ]:
            with self.subTest(left=left, right=right):
                self.assertFalse(compatible(left, right))
                service, qa = self.service()
                service.answer(left, 'MP')
                self.assertFalse(service.answer(right, 'MP')['cache_hit'])
        for left, right in [
            ('What is cache coherence?', 'Define cache coherence.'),
            ('What does SISD stand for?', 'What is the full form of SISD?'),
            ('What is UMA?', 'what is uma'),
        ]:
            self.assertTrue(compatible(left, right))

    def test_configuration_and_cosine_boundaries(self):
        self.assertEqual(SemanticCacheConfig(), SemanticCacheConfig(True, .75))
        for value in [-.1, 1, 1.1, float('nan'), True]:
            with self.assertRaises(ValueError):
                SemanticCacheConfig(True, value)
        self.assertIsNone(cosine([1], [1, 0]))
        self.assertEqual(cosine([1, 0], [1, 0]), 1)

    def test_environment_validation(self):
        with patch('services.semantic_cache.load_environment'), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(SemanticCacheConfig.from_environment(), SemanticCacheConfig(True, .75))
            for setting in [{'SEMANTIC_CACHE_ENABLED': 'yes'}, {'SEMANTIC_CACHE_THRESHOLD': 'x'},
                            {'SEMANTIC_CACHE_THRESHOLD': 'nan'}]:
                with patch.dict(os.environ, setting), self.assertRaises(ValueError):
                    SemanticCacheConfig.from_environment()
            with patch.dict(os.environ, {'SEMANTIC_CACHE_ENABLED': 'false', 'SEMANTIC_CACHE_THRESHOLD': '.8'}):
                self.assertEqual(SemanticCacheConfig.from_environment(), SemanticCacheConfig(False, .8))

    def test_cached_ollama_provenance_is_preserved(self):
        service, qa = self.service()
        from services.question_answering import NoAnswerFound
        qa.answer.side_effect = NoAnswerFound()
        service.fallback_service.respond.return_value = {
            'answer': 'expansion', 'source': 'llm_fallback', 'simulated': False,
            'provider': 'ollama', 'model': 'test-model',
            'sources': [{'excerpt': 'evidence', 'source': 'Files/course.txt'}],
        }
        first = service.answer('What does SISD stand for?', 'MP')
        second = service.answer('What is the full form of SISD?', 'MP')
        self.assertTrue(second['cache_hit'])
        self.assertEqual(second['sources'], first['sources'])
        self.assertEqual(second['provider'], 'ollama')
        service.fallback_service.respond.assert_called_once()
