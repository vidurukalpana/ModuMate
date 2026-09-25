"""Expiry, version changes, protected administration, and in-flight writes."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import os
import unittest
from unittest.mock import Mock, patch

from app import create_app
from services.answer_service import AnswerService
from services.cache_version import active_version
from services.question_answering import QuestionAnsweringService, ServiceUnavailable
from services.semantic_cache import SemanticCacheConfig
from utilities.cache_lfu import CacheLFU


class InvalidationTests(unittest.TestCase):
    def test_fixed_expiry_boundary_applies_to_exact_and_semantic(self):
        clock = Mock(return_value=0)
        cache = CacheLFU(2, 10, clock=clock)
        answer = {'answer': 'old'}
        cache.put(('MP', 'question'), answer)
        clock.return_value = 9
        self.assertIs(cache.get(('MP', 'question')), answer)
        clock.return_value = 10
        self.assertIsNone(cache.semantic_hit(('MP', 'question'), answer))
        self.assertIsNone(cache.get(('MP', 'question')))
        self.assertEqual(cache.candidates('MP'), [])
        self.assertEqual(cache.stats()['expirations'], 1)
        self.assertEqual(cache.stats()['evictions'], 0)
        self.assertEqual(cache.stats()['entries'], 0)

    def test_clear_endpoint_is_disabled_or_authenticated(self):
        qa = Mock()
        qa.answer.return_value = {'answer': 'answer', 'source': 'local_qa', 'sources': []}
        self.assertEqual(create_app(qa, Mock(), cache_admin_token='').test_client().post('/cache/clear').status_code, 403)
        app = create_app(qa, Mock(), cache_admin_token='test-secret')
        app.extensions['answer_service'].answer('question', 'MP')
        client = app.test_client()
        for auth in ['', 'Bearer wrong']:
            self.assertEqual(client.post('/cache/clear', headers={'Authorization': auth}).status_code, 401)
        self.assertEqual(app.extensions['answer_service'].cache_stats()['entries'], 1)
        result = client.post('/cache/clear', headers={'Authorization': 'Bearer test-secret'})
        self.assertEqual(result.json, {'removed': 1})
        self.assertEqual(app.extensions['answer_service'].cache_stats()['invalidation_reasons'], {'manual': 1})

    def test_inflight_answer_cannot_repopulate_after_manual_clear(self):
        entered, release = Event(), Event()
        qa = Mock()
        def answer(_):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test timed out')
            return {'answer': 'old answer', 'source': 'local_qa', 'sources': []}
        qa.answer.side_effect = answer
        service = AnswerService(qa, Mock())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(service.answer, 'question', 'MP')
            self.assertTrue(entered.wait(5))
            service.clear_cache()
            release.set()
            self.assertFalse(future.result()['cache_hit'])
        self.assertEqual(service.cache_stats()['entries'], 0)

    def test_material_and_config_changes_reset_retrieval_and_policy(self):
        qa, policy = Mock(), Mock()
        policy.before_answer.return_value = None
        qa.answer.return_value = {'answer': 'answer', 'source': 'local_qa', 'sources': []}
        service = AnswerService(qa, Mock(), question_policy=policy)
        with patch('services.answer_service.active_version', return_value=('notes1', 'config1')) as version:
            service.answer('question', 'MP')
            self.assertTrue(service.answer('question', 'MP')['cache_hit'])
            version.return_value = ('notes2', 'config1')
            self.assertFalse(service.answer('question', 'MP')['cache_hit'])
            version.return_value = ('notes2', 'config2')
            self.assertFalse(service.answer('question', 'MP')['cache_hit'])
        self.assertEqual(qa.reset.call_count, 2)
        self.assertEqual(policy.reset.call_count, 2)
        self.assertEqual(service.cache_stats()['invalidation_reasons'], {'materials_changed': 1, 'configuration_changed': 1})

    def test_material_change_during_generation_discards_cache_write(self):
        qa = Mock()
        service = AnswerService(qa, Mock())
        with patch('services.answer_service.active_version', side_effect=[('before', 'c'), ('after', 'c')]):
            qa.answer.return_value = {'answer': 'old', 'source': 'local_qa'}
            service.answer('question', 'MP')
        self.assertEqual(service.cache_stats()['entries'], 0)

    def test_fingerprint_reads_contents_and_detects_deletion(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Files').mkdir()
            spreadsheet = root / 'Multiprocessors.xlsx'
            spreadsheet.write_bytes(b'original')
            passage = root / 'Files' / 'notes.txt'
            passage.write_text('first')
            qa = QuestionAnsweringService(root)
            config = SemanticCacheConfig()
            before = active_version(qa, Mock(), config)
            passage.write_text('other')
            self.assertNotEqual(before, active_version(qa, Mock(), config))
            passage.unlink()
            self.assertNotEqual(before, active_version(qa, Mock(), config))
            spreadsheet.unlink()
            with self.assertRaises(OSError):
                active_version(qa, Mock(), config)

    def test_unreadable_materials_never_serve_old_cache(self):
        service = AnswerService(Mock(), Mock())
        service._cache.put(('MP', 'question'), {'answer': 'old'})
        with patch('services.answer_service.active_version', side_effect=OSError('private')):
            with self.assertRaises(ServiceUnavailable):
                service.answer('question', 'MP')
        self.assertEqual(service.cache_stats()['entries'], 0)

    def test_invalid_ttl_is_rejected(self):
        for value in [0, -1, True, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                CacheLFU(ttl_seconds=value)

    def test_ttl_environment_validation(self):
        from config import cache_ttl_from_environment
        with patch('config.load_environment'), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cache_ttl_from_environment(), 3600)
            for value in ['0', '-1', 'nan', 'inf', 'bad']:
                with patch.dict(os.environ, {'CACHE_TTL_SECONDS': value}), self.assertRaises(ValueError):
                    cache_ttl_from_environment()
            with patch.dict(os.environ, {'CACHE_TTL_SECONDS': '0.5'}):
                self.assertEqual(cache_ttl_from_environment(), .5)

    def test_retrieval_and_vocabulary_reset_rebuild_on_next_use(self):
        from services.question_policy import QuestionPolicy
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'notes.txt'
            path.write_text('XYZ is documented.')
            policy = QuestionPolicy(directory)
            self.assertIsNone(policy.before_answer('What is XYZ?'))
            path.write_text('ABC is documented.')
            policy.reset()
            self.assertIsNone(policy.before_answer('What is ABC?'))
            self.assertTrue(policy.before_answer('What is XYZ?')['abstained'])
        qa = QuestionAnsweringService()
        qa._model = Mock()
        qa.reset()
        self.assertIsNone(qa._model)
        model = Mock()
        with patch.object(qa, '_initialize', side_effect=lambda: setattr(qa, '_model', model)) as initialize:
            qa.encode_questions(['question'])
            initialize.assert_called_once()
            model.encode.assert_called_once_with(['question'])
