"""Bounded per-process metrics and privacy-conscious request completion logs."""

from collections import Counter, deque
from contextlib import contextmanager
import json
import logging
from threading import Lock
import time
from uuid import uuid4

from flask import g, has_request_context, request

SOURCES = {'local_qa', 'llm_fallback', 'simulated_fallback', 'question_policy'}
REASONS = {'low_retrieval_score', 'low_qa_score', 'no_extracted_answer',
           'invalid_retrieval_score', 'invalid_qa_score', 'answer_not_in_context',
           'no_accepted_answer', 'ambiguous_question', 'missing_course_material',
           'insufficient_course_relevance'}


@contextmanager
def stage(name):
    start = time.perf_counter()
    try:
        yield
    finally:
        if has_request_context() and hasattr(g, 'stage_seconds'):
            g.stage_seconds[name] = g.stage_seconds.get(name, 0.) + time.perf_counter() - start


def provider_call():
    if has_request_context() and hasattr(g, 'provider_calls'):
        g.provider_calls += 1


def error_category(name):
    if has_request_context():
        g.error_category = name


class Metrics:
    def __init__(self, sample_limit=256):
        self._lock = Lock()
        self._limit = sample_limit
        self._counts = Counter()
        self._timings = {}

    def record(self, event):
        with self._lock:
            self._counts['requests'] += 1
            self._counts[f"status_{event['status'] // 100}xx"] += 1
            self._counts['provider_calls'] += event['provider_calls']
            for field in ['source', 'cache_match_type', 'error_category', 'fallback_reason', 'endpoint']:
                if event.get(field):
                    self._counts[f"{field}:{event[field]}"] += 1
            if event.get('inflight_shared'):
                self._counts['inflight_shared'] += 1
            if event.get('abstained'):
                self._counts['abstentions'] += 1
            timings = {'request': event['duration_seconds'], **event['stages']}
            path = 'cache_' + event['cache_match_type'] if event.get('cache_match_type') else event.get('source')
            if path:
                timings['response:' + path] = event['duration_seconds']
            for name, seconds in timings.items():
                state = self._timings.setdefault(name, {'count': 0, 'total': 0., 'samples': deque(maxlen=self._limit)})
                state['count'] += 1
                state['total'] += seconds
                state['samples'].append(seconds)

    def snapshot(self):
        with self._lock:
            timing = {}
            for name, state in self._timings.items():
                samples = sorted(state['samples'])
                timing[name] = {'count': state['count'], 'mean_seconds': state['total'] / state['count'],
                                'recent_sample_count': len(samples),
                                'recent_p95_seconds': samples[max(0, (95 * len(samples) + 99) // 100 - 1)]}
            return {'scope': 'process', 'sample_limit': self._limit,
                    'counters': dict(self._counts), 'timings': timing}


def install_observability(app):
    metrics = Metrics()
    app.extensions['metrics'] = metrics
    app.logger.setLevel(logging.INFO)

    @app.before_request
    def begin():
        # Generate internally; untrusted incoming IDs are never copied to logs.
        g.request_id = uuid4().hex
        g.request_started = time.perf_counter()
        g.stage_seconds = {}
        g.provider_calls = 0

    @app.after_request
    def complete(response):
        response.headers['X-Request-ID'] = g.request_id
        body = response.get_json(silent=True) if request.endpoint == 'api.api' else None
        body = body if isinstance(body, dict) else {}
        source = body.get('source')
        match = body.get('cache_match_type')
        reason = body.get('fallback_reason') or body.get('reason')
        category = getattr(g, 'error_category', None)
        if not category and response.status_code >= 400:
            category = ('access_denied' if response.status_code in {401, 403} else
                        'not_ready' if request.endpoint == 'observability.ready' else
                        'invalid_request' if response.status_code < 500 else 'server_error')
        event = {
            'event': 'request_complete', 'request_id': g.request_id,
            'endpoint': request.url_rule.rule if request.url_rule else 'unmatched',
            'method': request.method if request.method in {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'} else 'other',
            'status': response.status_code,
            'duration_seconds': time.perf_counter() - g.request_started,
            'source': source if source in SOURCES else None,
            'cache_match_type': match if match in {'exact', 'semantic'} else None,
            'fallback_reason': reason if reason in REASONS else None,
            'abstained': body.get('abstained') is True,
            'inflight_shared': body.get('inflight_shared') is True,
            'provider_calls': g.provider_calls,
            'error_category': category, 'stages': dict(g.stage_seconds),
        }
        metrics.record(event)
        level = logging.ERROR if response.status_code >= 500 else logging.WARNING if response.status_code >= 400 else logging.INFO
        app.logger.log(level, json.dumps(event, separators=(',', ':')))
        return response
