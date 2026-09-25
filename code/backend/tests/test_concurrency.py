"""Deterministic concurrency tests; events hold requests at race boundaries."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import os
import time
import unittest
from unittest.mock import Mock, patch

from app import create_app
from services.answer_service import AnswerService
from services.concurrency import BackendBusy, ConcurrencyConfig, ProviderGate, WorkCoordinator
from services.llm_fallback import FallbackError


def until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('coordination timed out')
        time.sleep(.002)


class ConcurrencyTests(unittest.TestCase):
    def test_duplicate_result_sharing_and_copy_isolation(self):
        entered, release = Event(), Event()
        qa = Mock()
        def answer(_):
            entered.set()
            self.assertTrue(release.wait(3))
            return {'answer': 'answer', 'source': 'local_qa', 'sources': [{'excerpt': 'evidence'}]}
        qa.answer.side_effect = answer
        service = AnswerService(qa, Mock())
        with ThreadPoolExecutor(max_workers=4) as pool:
            leader = pool.submit(service.answer, 'question', 'MP')
            self.assertTrue(entered.wait(3))
            followers = [pool.submit(service.answer, 'question', 'MP') for _ in range(3)]
            until(lambda: service.concurrency.stats()['duplicate_waiters'] == 3)
            release.set()
            results = [leader.result()] + [f.result() for f in followers]
        qa.answer.assert_called_once()
        self.assertEqual(sum(r.get('inflight_shared', False) for r in results), 3)
        results[1]['sources'][0]['excerpt'] = 'changed'
        self.assertEqual(results[2]['sources'][0]['excerpt'], 'evidence')
        self.assertEqual(service.concurrency.stats()['active'], 0)
        self.assertEqual(service.concurrency.stats()['inflight_keys'], 0)

    def test_failure_releases_followers_and_all_slots(self):
        coordinator = WorkCoordinator(ConcurrencyConfig(1, 2, 1, 1))
        entered, release = Event(), Event()
        def fail():
            entered.set()
            release.wait(3)
            raise FallbackError('timeout')
        def run(op):
            with coordinator.admit():
                return coordinator.run('same', op)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, fail)
            entered.wait(3)
            second = pool.submit(run, fail)
            until(lambda: coordinator.stats()['duplicate_waiters'] == 1)
            release.set()
            for future in [first, second]:
                with self.assertRaises(FallbackError):
                    future.result()
        self.assertEqual(run(lambda: {'answer': 'retry'}), {'answer': 'retry'})
        self.assertEqual(coordinator.stats()['admitted'], 0)

    def test_busy_http_and_cache_hit_while_worker_occupied(self):
        entered, release = Event(), Event()
        qa = Mock()
        qa.answer.return_value = {'answer': 'warm', 'source': 'local_qa', 'sources': []}
        app = create_app(qa, Mock(), concurrency_config=ConcurrencyConfig(1, 1, 1, .02))
        service = app.extensions['answer_service']
        service.answer('cached', 'MP')
        def slow(_):
            entered.set()
            release.wait(3)
            return {'answer': 'slow', 'source': 'local_qa', 'sources': []}
        qa.answer.side_effect = slow
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(service.answer, 'slow', 'MP')
            entered.wait(3)
            self.assertTrue(service.answer('cached', 'MP')['cache_hit'])
            with self.assertLogs(app.logger, level='ERROR'):
                result = app.test_client().post('/api', json={'question': 'other', 'category': 'MP'})
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.json['code'], 'backend_busy')
            self.assertEqual(result.headers['Retry-After'], '1')
            release.set()
            running.result()

    def test_new_generation_does_not_join_old_flight(self):
        entered, release = Event(), Event()
        qa = Mock()
        def answer(_):
            if not entered.is_set():
                entered.set()
                release.wait(3)
                return {'answer': 'old', 'source': 'local_qa'}
            return {'answer': 'new', 'source': 'local_qa'}
        qa.answer.side_effect = answer
        service = AnswerService(qa, Mock())
        with ThreadPoolExecutor(max_workers=1) as pool:
            old = pool.submit(service.answer, 'question', 'MP')
            entered.wait(3)
            service.clear_cache()
            self.assertEqual(service.answer('question', 'MP')['answer'], 'new')
            release.set()
            old.result()
        self.assertEqual(service.answer('question', 'MP')['answer'], 'new')

    def test_provider_gate_releases_on_failure_and_times_out(self):
        gate = ProviderGate(ConcurrencyConfig(2, 1, 1, .01))
        with gate.slot():
            with self.assertRaises(BackendBusy):
                with gate.slot():
                    pass
        with self.assertRaises(RuntimeError):
            with gate.slot():
                raise RuntimeError()
        self.assertEqual(gate.stats()['active'], 0)
        self.assertEqual(gate.stats()['waiting'], 0)
        self.assertEqual(gate.stats()['busy_responses'], 1)

    def test_immediate_admission_rejection_and_config(self):
        coordinator = WorkCoordinator(ConcurrencyConfig(1, 0, 1, 1))
        with coordinator.admit():
            with self.assertRaises(BackendBusy):
                with coordinator.admit():
                    pass
        for kwargs in [{'active': 0}, {'waiting': -1}, {'ollama': True}, {'wait_seconds': float('nan')}]:
            with self.assertRaises(ValueError):
                ConcurrencyConfig(**kwargs)

    def test_follower_timeout_does_not_cancel_leader(self):
        coordinator = WorkCoordinator(ConcurrencyConfig(1, 1, 1, .02))
        entered, release = Event(), Event()
        def leader():
            with coordinator.admit():
                def work():
                    entered.set()
                    release.wait(3)
                    return {'answer': 'finished'}
                return coordinator.run('key', work)
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(leader)
            entered.wait(3)
            with self.assertRaises(BackendBusy), coordinator.admit():
                coordinator.run('key', lambda: None)
            release.set()
            self.assertEqual(running.result(), {'answer': 'finished'})
        self.assertEqual(coordinator.stats()['admitted'], 0)
        self.assertEqual(coordinator.stats()['duplicate_waiters'], 0)

    def test_environment_validation(self):
        with patch('services.concurrency.load_environment'), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ConcurrencyConfig.from_environment(), ConcurrencyConfig())
            for settings in [{'REQUEST_MAX_ACTIVE': 'zero'}, {'REQUEST_MAX_WAITING': '-1'},
                             {'OLLAMA_MAX_CONCURRENT': '0'}, {'REQUEST_WAIT_SECONDS': 'nan'}]:
                with patch.dict(os.environ, settings), self.assertRaises(ValueError):
                    ConcurrencyConfig.from_environment()
