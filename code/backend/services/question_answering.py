"""Lazy-loaded course retrieval and extractive question answering."""

from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict
import math
from pathlib import Path
from threading import Lock

from utilities.cache_lfu import CacheLFU
from services.retrieval import TOP_K, build_chunks, load_course
from services.confidence import ConfidencePolicy, DEFAULT_MIN_RETRIEVAL_SCORE

DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "text_files"
MIN_SIMILARITY = DEFAULT_MIN_RETRIEVAL_SCORE


class NoAnswerFound(Exception):
    """No suitable course context or answer was found."""

    def __init__(self, reason="no_accepted_answer"):
        super().__init__(reason)
        self.reason = reason


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
    def __init__(self, data_directory=DATA_DIRECTORY, *, confidence_policy=None):
        self._confidence_policy = confidence_policy or ConfidencePolicy()
        self._data_directory = Path(data_directory)
        self._lock = Lock()
        self._cache = CacheLFU()
        self._model = None

    @property
    def confidence_policy(self):
        return self._confidence_policy

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
        trace = {"outcome": "initializing", "candidates": [],
                 "confidence_policy": asdict(self.confidence_policy)}
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
            if not all(math.isfinite(float(score)) and -1.00001 <= float(score) <= 1.00001
                       for scores in (chunk_scores, summary_scores) for score in scores):
                trace["outcome"] = "invalid_retrieval_score"
                raise NoAnswerFound("invalid_retrieval_score")
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
                score = max(-1.0, min(1.0, score))
                rejection = self.confidence_policy.retrieval_rejection(score)
                candidate = {
                    "source": chunk.source, "topic": chunk.topic, "chunk_index": chunk.index,
                    "retrieval_score": score, "chunk_score": float(chunk_scores[index]),
                    "summary_score": float(summary_scores[self._owners[index]]),
                    "eligible": rejection is None, "accepted": False,
                    "rejection_reason": rejection,
                }
                trace["candidates"].append(candidate)
                if candidate["eligible"]:
                    candidates.append((chunk, candidate))
                if len(trace["candidates"]) >= TOP_K:
                    break
            if not candidates:
                trace["outcome"] = "below_retrieval_threshold"
                raise NoAnswerFound("low_retrieval_score")
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
                qa_score = float(result["score"])
                candidate["qa_score"] = qa_score if math.isfinite(qa_score) else None
                candidate["answer"] = answer
                rejection = self.confidence_policy.answer_rejection(answer, qa_score, context)
                candidate["rejection_reason"] = rejection
                candidate["accepted"] = rejection is None
                if candidate["accepted"] and (best is None or qa_score > best[1]["qa_score"]):
                    best = (answer, candidate)
            if best is None:
                trace["outcome"] = (
                    "qa_returned_no_answer" if all(not c.get("answer") for _, c in candidates)
                    else "no_candidate_passed_confidence"
                )
                reasons = {c["rejection_reason"] for _, c in candidates if c.get("answer")}
                if not reasons:
                    reason = "no_extracted_answer"
                elif len(reasons) == 1:
                    reason = {"below_qa_threshold": "low_qa_score"}.get(next(iter(reasons)), next(iter(reasons)))
                else:
                    reason = "no_accepted_answer"
                raise NoAnswerFound(reason)
            answer, selected = best
            trace["outcome"] = "answered"
            trace["selected"] = dict(selected)
            self._cache.put(question, answer)
            return answer
