"""Bounded admission, work slots and exact-question single-flight coordination."""

from concurrent.futures import Future, TimeoutError as FutureTimeout
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import math
import os
from threading import BoundedSemaphore, Lock

from config import load_environment
from services.observability import stage


class BackendBusy(Exception):
    """Capacity exhausted or a bounded wait elapsed."""


@dataclass(frozen=True)
class ConcurrencyConfig:
    active: int = 2
    waiting: int = 8
    ollama: int = 1
    wait_seconds: float = 120

    def __post_init__(self):
        for name, minimum in [('active', 1), ('waiting', 0), ('ollama', 1)]:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f'Concurrency {name} must be an integer >= {minimum}')
        if isinstance(self.wait_seconds, bool) or not isinstance(self.wait_seconds, (int, float)) or not math.isfinite(self.wait_seconds) or not 0 < self.wait_seconds <= 300:
            raise ValueError('REQUEST_WAIT_SECONDS must be in (0, 300]')

    @classmethod
    def from_environment(cls):
        load_environment()
        try:
            return cls(int(os.getenv('REQUEST_MAX_ACTIVE', '2')),
                       int(os.getenv('REQUEST_MAX_WAITING', '8')),
                       int(os.getenv('OLLAMA_MAX_CONCURRENT', '1')),
                       float(os.getenv('REQUEST_WAIT_SECONDS', '120')))
        except ValueError as error:
            raise ValueError(f'Invalid concurrency configuration: {error}') from error


class WorkCoordinator:
    def __init__(self, config):
        self.config = config
        self._admission = BoundedSemaphore(config.active + config.waiting)
        self._workers = BoundedSemaphore(config.active)
        self._lock = Lock()
        self._flights = {}
        self._admitted = self._active = self._shared = self._busy = self._followers = 0

    def _reject(self):
        with self._lock:
            self._busy += 1
        raise BackendBusy()

    @contextmanager
    def admit(self):
        if not self._admission.acquire(blocking=False):
            self._reject()
        with self._lock:
            self._admitted += 1
        try:
            yield
        finally:
            with self._lock:
                self._admitted -= 1
            self._admission.release()

    def run(self, key, operation):
        with self._lock:
            future = self._flights.get(key)
            leader = future is None
            if leader:
                future = self._flights[key] = Future()
            else:
                self._followers += 1
        if not leader:
            try:
                with stage('duplicate_wait'):
                    result = future.result(timeout=self.config.wait_seconds)
            except FutureTimeout:
                if future.done():
                    raise
                self._reject()
            finally:
                with self._lock:
                    self._followers -= 1
            with self._lock:
                self._shared += 1
            result = deepcopy(result)
            result.update(inflight_shared=True, cache_hit=False)
            result.pop('cache_match_type', None)
            result.pop('cache_similarity', None)
            return result
        try:
            with stage('admission_wait'):
                acquired = self._workers.acquire(timeout=self.config.wait_seconds)
            if not acquired:
                self._reject()
            try:
                with self._lock:
                    self._active += 1
                result = operation()
            finally:
                with self._lock:
                    self._active -= 1
                self._workers.release()
            future.set_result(deepcopy(result))
            return result
        except BaseException as error:
            future.set_exception(error)
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)

    def stats(self):
        with self._lock:
            return {'active': self._active, 'waiting': self._admitted - self._active,
                    'duplicate_waiters': self._followers,
                    'admitted': self._admitted, 'shared_results': self._shared,
                    'busy_responses': self._busy, 'inflight_keys': len(self._flights),
                    'max_active': self.config.active, 'max_waiting': self.config.waiting,
                    'wait_seconds': self.config.wait_seconds}


class ProviderGate:
    def __init__(self, config):
        self.config = config
        self._slots = BoundedSemaphore(config.ollama)
        self._lock = Lock()
        self._active = self._waiting = self._rejected = 0

    @contextmanager
    def slot(self):
        with self._lock:
            self._waiting += 1
        try:
            with stage('ollama_wait'):
                acquired = self._slots.acquire(timeout=self.config.wait_seconds)
        finally:
            with self._lock:
                self._waiting -= 1
        if not acquired:
            with self._lock:
                self._rejected += 1
            raise BackendBusy()
        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._slots.release()

    def stats(self):
        with self._lock:
            return {'active': self._active, 'waiting': self._waiting,
                    'busy_responses': self._rejected, 'max_active': self.config.ollama}
