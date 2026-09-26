"""Measure semantic reuse decisions on a small labelled development set."""

import argparse
import json
from pathlib import Path
import time

from services.semantic_cache import SemanticCacheConfig, compatible, cosine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--threshold', type=float, default=.75)
    parser.add_argument('--output', type=Path, default=Path('evaluation/reports/semantic-cache.json'))
    args = parser.parse_args()
    config = SemanticCacheConfig(True, args.threshold)
    from sentence_transformers import SentenceTransformer
    start = time.perf_counter()
    model = SentenceTransformer('all-MiniLM-L6-v2')
    initialization = time.perf_counter() - start
    dataset = json.loads(Path(__file__).with_name('semantic_pairs.json').read_text())
    results = []
    for pair in dataset['pairs']:
        start = time.perf_counter()
        guard = compatible(pair['cached'], pair['query'])
        vectors = model.encode([pair['cached'], pair['query']]) if guard else None
        similarity = cosine(*vectors) if guard else None
        reuse = similarity is not None and similarity > config.threshold
        results.append({**pair, 'guard_passed': guard, 'similarity': similarity, 'reuse': reuse,
                        'decision_seconds': time.perf_counter() - start})
    output = {'note': dataset['note'], 'threshold': config.threshold,
              'model': 'all-MiniLM-L6-v2', 'initialization_seconds': initialization,
              'correct_reuses': sum(r['reuse'] and r['equivalent'] for r in results),
              'incorrect_reuses': sum(r['reuse'] and not r['equivalent'] for r in results),
              'missed_reuses': sum(not r['reuse'] and r['equivalent'] for r in results),
              'results': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({k: v for k, v in output.items() if k != 'results'}, indent=2))


if __name__ == '__main__':
    main()
