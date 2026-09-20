"""Replay QA cutoffs on recorded candidates; never rerun retrieval or models."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from evaluation.run import summarize, text_scores
from services.confidence import ConfidencePolicy, valid_score


def replay(report, min_qa_score):
    policy = ConfidencePolicy(min_qa_score=min_qa_score)
    rows = deepcopy(report['results'])
    for row in rows:
        trace = row.get('retrieval')
        if not trace or trace['outcome'] in {'cache_hit', 'initializing', 'initialization_failed'}:
            raise ValueError('Sweep requires uncached, complete per-question diagnostics')
        if row['actual_behavior'] == 'error':
            raise ValueError('Resolve operational errors before comparing thresholds')
        # Keep retrieval decisions and non-score safety rejections fixed.
        eligible = [c for c in trace['candidates']
                    if c.get('eligible') and c.get('answer')
                    and c.get('rejection_reason') in (None, 'below_qa_threshold')
                    and valid_score(c.get('qa_score'), 0, 1)
                    and c['qa_score'] >= policy.min_qa_score]
        selected = max(eligible, key=lambda c: c['qa_score']) if eligible else None
        prediction = selected['answer'] if selected else ''
        fallback = 'simulated_fallback' if report.get('metadata', {}).get('fallback_mode') == 'simulated' else 'abstain'
        row['actual_behavior'] = 'answer' if selected else fallback
        row['behavior_match'] = row['actual_behavior'] == row['expected_behavior']
        if row['expected_behavior'] == 'answer':
            row.update(text_scores(prediction, row['reference_answers']))
    return {'min_qa_score': min_qa_score, **summarize(rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', type=Path, default=Path('evaluation/reports/confidence-sweep.json'))
    parser.add_argument('--thresholds', type=float, nargs='+', default=[0, .1, .15, .2, .3, .5, .6, .8])
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding='utf-8'))
    try:
        results = [replay(report, threshold) for threshold in args.thresholds]
    except ValueError as error:
        parser.error(str(error))
    output = {
        'input_report_sha256': hashlib.sha256(args.report.read_bytes()).hexdigest(),
        'cases_sha256': report['metadata']['cases_sha256'],
        'fixed_retrieval_threshold': report['metadata']['retrieval_threshold'],
        'note': 'Development-set QA-score replay, not calibration or held-out accuracy. Retrieval, top-k candidates, and other rejection rules stay fixed.',
        'results': results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print('QA cutoff | exact match | answer return rate | unsupported answers')
    for row in results:
        print(f"{row['min_qa_score']:.2f} | {row['answer_exact_match']:.1%} | "
              f"{row['answer_return_rate']:.1%} | {row['unsupported_answer_count']}")
    print(f'Report: {args.output.resolve()}')


if __name__ == '__main__':
    main()
