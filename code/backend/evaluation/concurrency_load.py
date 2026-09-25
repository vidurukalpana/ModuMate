"""In-process concurrent API benchmark; not a production server benchmark."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import resource
import statistics
import sys
import time

from app import create_app
from services.concurrency import ConcurrencyConfig
from services.llm_fallback import FallbackConfig, LLMFallback
from services.question_answering import QuestionAnsweringService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', nargs='+', type=int, default=[1, 2, 4, 8])
    parser.add_argument('--requests', type=int, default=24)
    parser.add_argument('--fallback-mode', choices=['simulated', 'ollama'], default='simulated')
    parser.add_argument('--output', type=Path, default=Path('evaluation/reports/concurrency-load.json'))
    args = parser.parse_args()
    if args.requests < 1 or any(w < 1 for w in args.workers):
        parser.error('Workers and requests must be positive')
    config = ConcurrencyConfig.from_environment()
    qa = QuestionAnsweringService()
    warm = create_app(qa, LLMFallback(FallbackConfig(mode='simulated')))
    warm.test_client().post('/api', json={'question': 'What is UMA?', 'category': 'MP'})
    questions = ['What does SISD stand for?', 'What is UMA?', 'What is cache coherence?']
    runs = []
    for workers in args.workers:
        fallback = LLMFallback(FallbackConfig.from_environment(mode=args.fallback_mode), concurrency_config=config)
        app = create_app(qa, fallback, concurrency_config=config)
        def call(i):
            start = time.perf_counter()
            with app.test_client() as client:
                response = client.post('/api', json={'question': questions[(i // 4) % len(questions)], 'category': 'MP'})
                body = response.json
            return {'seconds': time.perf_counter() - start, 'status': response.status_code,
                    'shared': body.get('inflight_shared', False), 'cache_hit': body.get('cache_hit', False)}
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(call, range(args.requests)))
        elapsed = time.perf_counter() - started
        latencies = sorted(r['seconds'] for r in results)
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        runs.append({'workers': workers, 'requests': args.requests, 'seconds': elapsed,
                     'requests_per_second': args.requests / elapsed,
                     'mean_seconds': statistics.mean(latencies),
                     'p95_seconds': latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)],
                     'errors': sum(r['status'] >= 400 for r in results),
                     'busy': sum(r['status'] == 503 for r in results),
                     'shared': sum(r['shared'] for r in results),
                     'peak_process_rss_bytes': peak if sys.platform == 'darwin' else peak * 1024,
                     'cache': app.extensions['answer_service'].cache_stats(),
                     'concurrency': app.extensions['answer_service'].concurrency.stats()})
    report = {'note': 'Warm local models; fresh cache per run; fixed repeated sequence. In-process API timings, not production throughput. RSS is cumulative process high-water mark, not per-run allocation. Simulated fallback is not Ollama latency.',
              'fallback_mode': args.fallback_mode, 'runs': runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
