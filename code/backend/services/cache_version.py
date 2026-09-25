"""Fingerprint course bytes and active answer-producing configuration."""

from dataclasses import asdict
import hashlib
import json

from services.question_answering import QuestionAnsweringService
from services import question_answering, question_policy
from services.llm_fallback import LLMFallback, SYSTEM_PROMPT
from services.retrieval import TOP_K, CHUNK_WORDS, CHUNK_OVERLAP, CONTEXT_WORDS


def active_version(qa, fallback, semantic):
    materials = hashlib.sha256()
    configuration = {'semantic': asdict(semantic), 'retrieval': [TOP_K, CHUNK_WORDS, CHUNK_OVERLAP, CONTEXT_WORDS]}
    if isinstance(qa, QuestionAnsweringService):
        directory = qa._data_directory
        paths = [directory / 'Multiprocessors.xlsx', *sorted((directory / 'Files').glob('*.txt'))]
        for path in paths:
            materials.update(str(path.relative_to(directory)).encode())
            materials.update(b'\0')
            materials.update(path.read_bytes())
        configuration['confidence'] = asdict(qa.confidence_policy)
        configuration['models'] = [question_answering.EMBEDDING_MODEL, question_answering.QA_MODEL]
        configuration['course_relevance'] = question_policy.MIN_COURSE_RELEVANCE
    if isinstance(fallback, LLMFallback):
        configuration['fallback'] = asdict(fallback.config)
        configuration['prompt'] = SYSTEM_PROMPT
    return materials.hexdigest(), hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
