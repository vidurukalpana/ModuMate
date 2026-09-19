"""Run the course evaluation through Flask's in-process HTTP test client."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = Path(__file__).with_name('cases.json')


def normalize(text):
    """Normalize case, punctuation and English articles for lexical scoring."""
    text = re.sub(r'[^\w\s]', ' ', text.casefold())
    return ' '.join(re.sub(r'\b(a|an|the)\b', ' ', text).split())


def text_scores(prediction, references):
    """Best-reference exact match and bag-of-words F1; not semantic correctness."""
    predicted = normalize(prediction).split()
    exact, f1 = 0.0, 0.0
    for reference in references:
        expected = normalize(reference).split()
        exact = max(exact, float(predicted == expected))
        overlap = sum((Counter(predicted) & Counter(expected)).values())
        score = 2 * overlap / (len(predicted) + len(expected)) if overlap else 0.0
        f1 = max(f1, score)
    return {'exact_match': exact, 'token_f1': f1}


def load_cases(path=DEFAULT_CASES, data_directory=ROOT / 'text_files'):
    dataset = json.loads(Path(path).read_text(encoding='utf-8'))
    if dataset.get('version') != 1 or not dataset.get('cases'):
        raise ValueError('Expected a non-empty version 1 evaluation dataset')
    seen = set()
    for case in dataset['cases']:
        case_id = case['id']
        if case_id in seen:
            raise ValueError(f'Duplicate case ID: {case_id}')
        seen.add(case_id)
        if case['kind'] not in {'direct', 'paraphrase', 'comparison', 'ambiguous', 'unsupported'}:
            raise ValueError(f'{case_id}: unknown kind')
        expected = {'ambiguous': 'clarify', 'unsupported': 'abstain'}.get(case['kind'], 'answer')
        if case['expected_behavior'] != expected:
            raise ValueError(f'{case_id}: inconsistent expected behavior')
        if case['category'] != 'MP' or not isinstance(case['question'], str) or not case['question'].strip():
            raise ValueError(f'{case_id}: invalid request')
        references = case['reference_answers']
        if not isinstance(references, list) or any(not isinstance(a, str) or not normalize(a) for a in references):
            raise ValueError(f'{case_id}: invalid reference answers')
        if expected == 'answer' and (not references or not case['sources']):
            raise ValueError(f'{case_id}: answer needs references and sources')
        if expected != 'answer' and references:
            raise ValueError(f'{case_id}: non-answer case cannot have answer references')
        for source in case['sources']:
            source_path = (data_directory / source['path']).resolve()
            if not source_path.is_relative_to(data_directory.resolve()):
                raise ValueError(f'{case_id}: source path escapes course directory')
            if not source['quote'] or source['quote'] not in source_path.read_text(encoding='utf-8'):
                raise ValueError(f'{case_id}: supporting quotation not found')
    return dataset


def classify_response(status, body):
    if not isinstance(body, dict):
        return 'error'
    # Reserved extension for a future explicit clarification API contract.
    if status == 200 and body.get('needs_clarification') is True and isinstance(body.get('clarification'), str) and body['clarification'].strip():
        return 'clarify'
    if status == 200 and isinstance(body.get('answer'), str) and body['answer'].strip():
        return 'answer'
    if status == 422 and isinstance(body.get('error'), str) and body['error'].strip():
        return 'abstain'
    return 'error'


def summarize(rows):
    answer_rows = [r for r in rows if r['expected_behavior'] == 'answer']
    non_answer_rows = [r for r in rows if r['expected_behavior'] != 'answer']
    def mean(values):
        return statistics.mean(values) if values else None
    return {
        'total': len(rows),
        'operational_errors': sum(r['actual_behavior'] == 'error' for r in rows),
        'answer_case_count': len(answer_rows),
        'answer_exact_match': mean([r['exact_match'] for r in answer_rows]),
        'answer_token_f1': mean([r['token_f1'] for r in answer_rows]),
        'answer_return_rate': mean([float(r['actual_behavior'] == 'answer') for r in answer_rows]),
        'non_answer_behavior_accuracy': mean([float(r['behavior_match']) for r in non_answer_rows]),
        'unsupported_answer_count': sum(r['expected_behavior'] == 'abstain' and r['actual_behavior'] == 'answer' for r in rows),
        'clarification_matches': sum(r['expected_behavior'] == 'clarify' and r['actual_behavior'] == 'clarify' for r in rows),
    }


def evaluate(dataset, client):
    results = []
    for case in dataset['cases']:
        start = time.perf_counter()
        response = client.post('/api', json={'question': case['question'], 'category': case['category']})
        elapsed = time.perf_counter() - start
        body = response.get_json(silent=True)
        actual = classify_response(response.status_code, body)
        prediction = body['answer'] if actual == 'answer' else ''
        result = {
            **case, 'http_status': response.status_code, 'response': body,
            'actual_behavior': actual,
            'behavior_match': actual == case['expected_behavior'],
            'elapsed_seconds': round(elapsed, 4),
            'exact_match': None, 'token_f1': None,
        }
        if case['expected_behavior'] == 'answer':
            result.update(text_scores(prediction, case['reference_answers']))
        results.append(result)
    return {
        'summary': summarize(results),
        'by_kind': {kind: summarize([r for r in results if r['kind'] == kind])
                    for kind in sorted({r['kind'] for r in results})},
        'results': results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=DEFAULT_CASES)
    parser.add_argument('--output', type=Path, default=ROOT / 'evaluation/reports/latest.json')
    parser.add_argument('--validate-only', action='store_true', help='Check cases and source quotes without loading models')
    args = parser.parse_args()
    dataset = load_cases(args.cases)
    if args.validate_only:
        print(f"Validated {len(dataset['cases'])} source-grounded cases")
        return 0

    from app import create_app
    from importlib.metadata import version
    from services.question_answering import MIN_SIMILARITY

    report = evaluate(dataset, create_app().test_client())
    report['metadata'] = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'dataset_version': dataset['version'],
        'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        'course': dataset['course'],
        'scope': dataset['scope'],
        'retrieval_threshold': MIN_SIMILARITY,
        'packages': {name: version(name) for name in ['Flask', 'transformers', 'sentence-transformers', 'torch']},
        'source_sha256': {str(p.relative_to(ROOT / 'text_files')): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((ROOT / 'text_files').rglob('*')) if p.suffix in {'.txt', '.xlsx'}},
        'timing_note': 'First request includes model initialization; sequential requests use the normal cache. Not a load benchmark.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], indent=2))
    print(f'Report: {args.output.resolve()}')
    # Poor quality is baseline data; transport/model failures are execution errors.
    return 2 if report['summary']['operational_errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
