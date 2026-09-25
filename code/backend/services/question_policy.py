"""Conservative English-language guards for a stateless course tutor.

These rules identify explicit missing subjects/entities, not general semantic
correctness. Borderline questions remain eligible for the normal QA/LLM path.
"""

import math
from pathlib import Path
import re
from threading import Lock

DATA_DIRECTORY = Path(__file__).resolve().parents[1] / 'text_files' / 'Files'
MIN_COURSE_RELEVANCE = 0.20
SUGGESTIONS = ['UMA and NUMA', "Flynn's classification", 'Cache coherence', 'Message-passing multiprocessors']


def non_answer(reason, text):
    return {'answer': text, 'source': 'question_policy', 'reason': reason,
            'cache_hit': False, 'sources': [], 'suggested_topics': list(SUGGESTIONS), 'abstained': True}


class QuestionPolicy:
    def __init__(self, data_directory=DATA_DIRECTORY):
        self.data_directory = Path(data_directory)
        self._vocabulary = None
        self._lock = Lock()

    def reset(self):
        with self._lock:
            self._vocabulary = None

    def _known_terms(self):
        with self._lock:
            if self._vocabulary is None:
                paths = sorted(self.data_directory.glob('*.txt'))
                if not paths:
                    raise ValueError('Course text files are missing')
                text = ' '.join(p.stem.replace('_', ' ') + ' ' + p.read_text(encoding='utf-8') for p in paths)
                self._vocabulary = set(re.findall(r'[a-z0-9]+', text.casefold()))
            return self._vocabulary

    def before_answer(self, question):
        text = question.strip().rstrip('?.!').casefold()
        # Entire-question patterns avoid blocking questions that supply a subject.
        unresolved = [
            r'(?:which|what) (?:one|of (?:them|these|those)) (?:is|are) .+',
            r'(?:explain|describe|clarify)(?: more about)? (?:it|this|that|the same)(?: (?:protocol|system|architecture|concept|topic))?',
            r'how (?:many|much|long|fast) .+ (?:does|do|will|would) (?:it|they|that|this) (?:take|need|use|run)',
            r'(?:what|how|why) (?:is|are|does|do) (?:it|that|this|they)(?: work| mean)?',
            r'(?:compare|explain the difference between) (?:them|these|those|the two)',
        ]
        if any(re.fullmatch(pattern, text) for pattern in unresolved):
            comparison = text.startswith(('which', 'compare', 'explain the difference', 'what one', 'what of'))
            message = ('This question does not identify the systems being compared.' if comparison
                       else 'This question does not identify the architecture, operation, or protocol being discussed.')
            return non_answer('ambiguous_question', message)

        # Require explicit vocabulary support for named acronyms/product IDs.
        # Ignore ordinary words in an ALL-CAPS question, but retain mixed IDs.
        identifiers = []
        technical_context = bool(re.search(r'\b(?:processor|processors|cpu|cache|architecture|chip|hardware)\b', text))
        ordinary_emphasis = {'PLEASE', 'EXPLAIN', 'WHAT', 'WHY', 'HOW', 'COMPARE', 'AND', 'OR', 'NOT', 'THE', 'IS', 'DO', 'DOES'}
        for word in re.findall(r'\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\b', question):
            acronym = len(word) >= 2 and word.isupper() and not question.isupper() and word not in ordinary_emphasis
            product_id = technical_context and any(c.isdigit() for c in word)
            if acronym or product_id:
                identifiers.append(word)
        # Lowercase hyphenated architecture names remain explicit identifiers;
        # do not mistake ordinary modifiers (e.g. "improving processor") for names.
        identifiers += re.findall(
            r'\b([a-z][a-z0-9]*-[a-z0-9-]+)\s+(?:processor|cpu|architecture)\b', text)
        if identifiers:
            known = self._known_terms()
            missing = [term for term in identifiers
                       if not all(part in known for part in re.findall(r'[a-z0-9]+', term.casefold()))]
            if missing:
                return non_answer('missing_course_material',
                    'I could not locate '
                    + ', '.join(dict.fromkeys(missing))
                    + ' by name in the supplied multiprocessor notes. Answers are limited to those notes.')
        return None

    def after_retrieval(self, reason, trace):
        if reason != 'low_retrieval_score' or not trace:
            return None
        scores = [c.get('retrieval_score') for c in trace.get('candidates', [])]
        if not scores or any(
            not isinstance(score, (int, float)) or not math.isfinite(score)
            for score in scores
        ):
            return None
        if max(scores) < MIN_COURSE_RELEVANCE:
            return non_answer('insufficient_course_relevance',
                'I could not find relevant evidence in the supplied Computer Architecture '
                'multiprocessor notes. Answers are limited to those notes.')
        return None
