"""Capacity configuration, exact accounting, privacy and concurrent snapshots."""

from concurrent.futures import ThreadPoolExecutor
import os
import unittest
from unittest.mock import Mock, patch

from app import create_app
from config import cache_capacity_from_environment
from evaluation.cache_workload import repeated_cases
from utilities.cache_lfu import CacheLFU


class CacheMetricTests(unittest.TestCase):
    def test_configuration(self):
        with patch('config.load_environment'), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cache_capacity_from_environment(), 10)
            for value in ['0', '-2', 'x', '1.5', '']:
                with patch.dict(os.environ, {'CACHE_CAPACITY': value}), self.assertRaisesRegex(ValueError, 'CACHE_CAPACITY'):
                    create_app(Mock(), Mock())
            with patch.dict(os.environ, {'CACHE_CAPACITY': '3'}):
                self.assertEqual(create_app(Mock(), Mock()).test_client().get('/cache/stats').json['capacity'], 3)
        for capacity in [True, 1.5, 0, -1]:
            with self.assertRaises(ValueError):
                CacheLFU(capacity)

    def test_counter_semantics_and_snapshot_isolation(self):
        cache = CacheLFU(1)
        self.assertEqual(cache.stats()['hit_rate'], 0)
        cache.get('missing')
        cache.put('a', 'answer')
        cache.put('a', 'updated')
        cache.get('a')
        cache.put('b', 'answer')
        expected = dict(ttl_seconds=3600, expirations=0, invalidations=0, invalidated_entries=0, invalidation_reasons={}, exact_hits=1, semantic_hits=0, capacity=1, entries=1, hits=1, misses=1, hit_rate=.5, inserts=2, updates=1, evictions=1)
        self.assertEqual(cache.stats(), expected)
        cache.stats()['hits'] = 100
        self.assertEqual(cache.stats(), expected)

    def test_policy_bypass_concurrent_hits_and_private_endpoint(self):
        qa = Mock()
        qa.answer.return_value = {'answer': 'private answer', 'source': 'local_qa', 'sources': []}
        app = create_app(qa, Mock(), cache_capacity=2)
        service = app.extensions['answer_service']
        client = app.test_client()
        client.post('/api', json={'question': 'Compare them', 'category': 'MP'})
        client.post('/api', json={})
        self.assertEqual(service.cache_stats()['misses'], 0)
        service.answer('private question', 'MP')
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: service.answer('private question', 'MP'), range(100)))
        response = client.get('/cache/stats')
        self.assertEqual(response.json['hits'], 100)
        self.assertEqual(response.json['misses'], 1)
        self.assertNotIn('private', response.get_data(as_text=True))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        qa.answer.assert_called_once()

    def test_repeat_workload_is_identical_for_each_capacity(self):
        self.assertEqual(repeated_cases(['a', 'b']), ['a', 'a', 'b', 'b'] * 2)
