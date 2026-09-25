"""Semantic hits must preserve evidence and never cross intent/category boundaries."""

import os
import unittest
from unittest.mock import Mock, patch

from services.answer_service import AnswerService
from services.semantic_cache import SemanticCacheConfig, compatible, cosine


class SemanticTests(unittest.TestCase):
    def service(self, enabled=True):
        qa = Mock()
        qa.answer.return_value = {'answer': 'expansion', 'source': 'local_qa',
                                  'sources': [{'source': 'Files/course.txt', 'excerpt': 'evidence'}]}
        qa.encode_questions.return_value = [[1., 0.], [1., 0.]]
        policy = Mock(before_answer=Mock(return_value=None), after_retrieval=Mock(return_value=None))
        return AnswerService(qa, Mock(), question_policy=policy, cache_capacity=1,
                             semantic_config=SemanticCacheConfig(enabled, .9)), qa

    def test_hit_preserves_citations_without_new_entry_or_qa(self):
        service, qa = self.service()
        service.answer('What does SISD stand for?', 'MP')
        result = service.answer('What is the full form of SISD?', 'MP')
        self.assertEqual(result['cache_match_type'], 'semantic')
        self.assertEqual(result['cache_similarity'], 1.)
        self.assertEqual(result['source'], 'local_qa')
        self.assertEqual(result['sources'][0]['excerpt'], 'evidence')
        qa.answer.assert_called_once()
        self.assertEqual(service.cache_stats()['semantic_hits'], 1)
        self.assertEqual(service.cache_stats()['misses'], 1)
        self.assertEqual(service.cache_stats()['entries'], 1)
        service.answer('What does SISD stand for?', 'MP')
        self.assertEqual(qa.encode_questions.call_count, 1)
        self.assertEqual(service.cache_stats()['exact_hits'], 1)

    def test_disabled_and_category_mismatch_skip_encoder(self):
        for enabled, category in [(False, 'MP'), (True, 'other')]:
            service, qa = self.service(enabled)
            service.answer('What does SISD stand for?', 'MP')
            self.assertFalse(service.answer('What is the full form of SISD?', category)['cache_hit'])
            qa.encode_questions.assert_not_called()

    def test_low_similarity_and_invalid_vectors_miss(self):
        for vector in [[0., 1.], [float('nan'), 0.], [0., 0.]]:
            service, qa = self.service()
            service.answer('What does SISD stand for?', 'MP')
            qa.encode_questions.return_value = [[1., 0.], vector]
            self.assertFalse(service.answer('What is the full form of SISD?', 'MP')['cache_hit'])
            self.assertEqual(service.cache_stats()['misses'], 2)

    def test_evicted_snapshot_cannot_return_stale_answer(self):
        service, qa = self.service()
        service.answer('What does SISD stand for?', 'MP')
        def encode(_):
            with service._lock:
                service._cache.put(('MP', 'replacement'), {'answer': 'replacement'})
            return [[1., 0.], [1., 0.]]
        qa.encode_questions.side_effect = encode
        self.assertFalse(service.answer('What is the full form of SISD?', 'MP')['cache_hit'])
        self.assertEqual(service.cache_stats()['semantic_hits'], 0)

    def test_conflicting_intent_subject_and_unknown_forms_are_blocked(self):
        for left, right in [
            ('What is UMA?', 'What is NUMA?'),
            ('What are the advantages of UMA?', 'What are the disadvantages of UMA?'),
            ('What is cache coherence?', 'What is not cache coherence?'),
            ('What is an L1 cache?', 'What is an L2 cache?'),
            ('Compare UMA and NUMA', 'Compare NUMA and UMA'),
            ('What does SISD stand for?', 'What is SISD?'),
        ]:
            self.assertFalse(compatible(left, right))
        self.assertTrue(compatible('What is cache coherence?', 'Define cache coherence.'))

    def test_configuration_and_cosine_boundaries(self):
        for value in [0, 1.1, float('nan'), True]:
            with self.assertRaises(ValueError):
                SemanticCacheConfig(True, value)
        self.assertIsNone(cosine([1], [1, 0]))
        self.assertEqual(cosine([1, 0], [1, 0]), 1)

    def test_environment_validation(self):
        with patch('services.semantic_cache.load_environment'), patch.dict(os.environ, {}, clear=True):
            self.assertFalse(SemanticCacheConfig.from_environment().enabled)
            for setting in [{'SEMANTIC_CACHE_ENABLED': 'yes'}, {'SEMANTIC_CACHE_THRESHOLD': 'x'},
                            {'SEMANTIC_CACHE_THRESHOLD': 'nan'}]:
                with patch.dict(os.environ, setting), self.assertRaises(ValueError):
                    SemanticCacheConfig.from_environment()
            with patch.dict(os.environ, {'SEMANTIC_CACHE_ENABLED': 'true', 'SEMANTIC_CACHE_THRESHOLD': '.95'}):
                self.assertEqual(SemanticCacheConfig.from_environment(), SemanticCacheConfig(True, .95))

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
