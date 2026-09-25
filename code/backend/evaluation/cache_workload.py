"""Compare cache capacities on one repeat-question workload through the API."""

import argparse
import json
from pathlib import Path

from app import create_app
from evaluation.run import evaluate, load_cases
from services.llm_fallback import FallbackConfig, LLMFallback
from services.question_answering import QuestionAnsweringService


def repeated_cases(cases):
    # Immediate repeats measure reuse; later rounds reveal capacity pressure.
    return [case for _ in range(2) for case in cases for _ in range(2)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capacities', nargs='+', type=int, default=[2, 5, 10, 20])
    parser.add_argument('--fallback-mode', choices=['simulated', 'ollama'], default='simulated')
    parser.add_argument('--output', type=Path, default=Path('evaluation/reports/cache-workload.json'))
    args = parser.parse_args()
    if any(capacity < 1 for capacity in args.capacities):
        parser.error('Capacities must be positive integers')
    dataset = load_cases()
    workload = {'cases': repeated_cases(dataset['cases'])}
    qa = QuestionAnsweringService()
    fallback = LLMFallback(FallbackConfig.from_environment(mode=args.fallback_mode))
    runs = []
    for capacity in args.capacities:
        app = create_app(qa, fallback, cache_capacity=capacity)
        report = evaluate(workload, app.test_client())
        runs.append({'capacity': capacity, **report})
        print(json.dumps({'capacity': capacity, 'stats': report['cache_stats']}))
    output = {
        'fallback_mode': args.fallback_mode,
        'note': 'Two rounds of all cases, each immediately repeated. Fresh cache per capacity; model instance is shared. First run includes cold initialization. Timings are descriptive, not a controlled speedup or load benchmark.',
        'runs': runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + '\n')
    return 2 if any(run['summary']['operational_errors'] for run in runs) else 0


if __name__ == '__main__':
    raise SystemExit(main())
