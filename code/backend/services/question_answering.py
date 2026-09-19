"""Lazy-loaded course retrieval and extractive question answering."""

from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from threading import Lock

from utilities.cache_lfu import CacheLFU
from services.retrieval import TOP_K, build_chunks, load_course

DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "text_files"
MIN_SIMILARITY = 0.5


class NoAnswerFound(Exception):
    """No suitable course context or answer was found."""


class ServiceUnavailable(Exception):
    """Models or course data could not be initialized."""


_trace = ContextVar("retrieval_trace", default=None)


def clear_retrieval_trace():
    """Clear diagnostics before an evaluation request, including rejected requests."""
    _trace.set(None)


def get_retrieval_trace():
    """Return diagnostics for this execution context, without changing the API."""
    return deepcopy(_trace.get())


def load_passages(data_directory):
    """Compatibility helper for consumers needing whole source passages."""
    records = load_course(data_directory)
    return [r[1] for r in records], [r[3] for r in records]


class QuestionAnsweringService:
    def __init__(self, data_directory=DATA_DIRECTORY):
        self._data_directory = Path(data_directory)
        self._lock = Lock()
        self._cache = CacheLFU()
        self._model = None

    def _initialize(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer, util
            from transformers import pipeline

            records = load_course(self._data_directory)
            chunks, owners = build_chunks(records)
            model = SentenceTransformer("all-MiniLM-L6-v2")
            qa_model = pipeline(
                "question-answering", model="twmkn9/bert-base-uncased-squad2"
            )
            embeddings = model.encode([f"{chunk.topic}\n{chunk.text}" for chunk in chunks])
            summary_embeddings = model.encode([r[1] for r in records])
        except Exception as exc:
            raise ServiceUnavailable() from exc
        self._chunks = chunks
        self._owners = owners
        self._summary_embeddings = summary_embeddings
        self._qa_model = qa_model
        self._embeddings = embeddings
        self._cos_sim = util.cos_sim
        self._model = model

    def answer(self, question):
        trace = {"outcome": "initializing", "candidates": []}
        _trace.set(trace)
        # Serialize initialization, inference, and cache mutations per process.
        with self._lock:
            cached = self._cache.get(question)
            if cached is not None:
                trace["outcome"] = "cache_hit"
                return cached
            try:
                self._initialize()
            except ServiceUnavailable:
                trace["outcome"] = "initialization_failed"
                raise
            encoded = self._model.encode(question)
            chunk_scores = self._cos_sim(self._embeddings, encoded).flatten()
            summary_scores = self._cos_sim(self._summary_embeddings, encoded).flatten()
            # Preserve summary search while adding direct evidence search.
            ranked = sorted(
                range(len(self._chunks)),
                key=lambda i: (
                    max(float(chunk_scores[i]), float(summary_scores[self._owners[i]])),
                    float(chunk_scores[i]),
                ),
                reverse=True,
            )
            candidates = []
            seen = set()
            for index in ranked:
                chunk = self._chunks[index]
                # Duplicate course passages should not consume the candidate budget.
                key = " ".join(chunk.text.split()).casefold()
                if key in seen:
                    continue
                seen.add(key)
                score = max(float(chunk_scores[index]), float(summary_scores[self._owners[index]]))
                candidate = {
                    "source": chunk.source, "topic": chunk.topic, "chunk_index": chunk.index,
                    "retrieval_score": score, "chunk_score": float(chunk_scores[index]),
                    "summary_score": float(summary_scores[self._owners[index]]),
                    "eligible": score >= MIN_SIMILARITY,
                }
                trace["candidates"].append(candidate)
                if candidate["eligible"]:
                    candidates.append((chunk, candidate))
                if len(trace["candidates"]) >= TOP_K:
                    break
            if not candidates:
                trace["outcome"] = "below_retrieval_threshold"
                raise NoAnswerFound()
            best = None
            evaluated_contexts = {}
            for chunk, candidate in candidates:
                context = chunk.context or chunk.text
                if context in evaluated_contexts:
                    result = evaluated_contexts[context]
                else:
                    result = self._qa_model(
                        question=question, context=context,
                        handle_impossible_answer=True,
                    )
                    evaluated_contexts[context] = result
                answer = result["answer"].strip()
                candidate["qa_score"] = float(result["score"])
                candidate["answer"] = answer
                if answer and (best is None or candidate["qa_score"] > best[1]["qa_score"]):
                    best = (answer, candidate)
            if best is None:
                trace["outcome"] = "qa_returned_no_answer"
                raise NoAnswerFound()
            answer, selected = best
            trace["outcome"] = "answered"
            trace["selected"] = dict(selected)
            self._cache.put(question, answer)
            return answer
