"""Lazy-loaded course retrieval and extractive question answering."""

from pathlib import Path
from threading import Lock

from utilities.cache_lfu import CacheLFU

DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "text_files"
MIN_SIMILARITY = 0.5


class NoAnswerFound(Exception):
    """No suitable course context or answer was found."""


class ServiceUnavailable(Exception):
    """Models or course data could not be initialized."""


def load_passages(data_directory):
    """Validate the dataset and read complete passages, preserving filenames."""
    import pandas as pd

    dataset = pd.read_excel(data_directory / "Multiprocessors.xlsx")
    columns = ["Summary", "File Name"]
    if dataset.empty or not set(columns).issubset(dataset.columns):
        raise ValueError("Course dataset is empty or missing required columns")
    summaries, passages = [], []
    passage_directory = (data_directory / "Files").resolve()
    for summary, filename in dataset[columns].itertuples(index=False, name=None):
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("Course summary must be a non-empty string")
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Course filename must be a non-empty string")
        path = (passage_directory / f"{filename}.txt").resolve()
        if path.parent != passage_directory:
            raise ValueError("Course passage must be inside the Files directory")
        passage = path.read_text(encoding="utf-8").strip()
        if not passage:
            raise ValueError("Course passage is empty")
        summaries.append(summary)
        passages.append(passage)
    return summaries, passages


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

            summaries, passages = load_passages(self._data_directory)
            model = SentenceTransformer("all-MiniLM-L6-v2")
            qa_model = pipeline(
                "question-answering", model="twmkn9/bert-base-uncased-squad2"
            )
            embeddings = model.encode(summaries)
        except Exception as exc:
            raise ServiceUnavailable() from exc
        self._passages = passages
        self._qa_model = qa_model
        self._embeddings = embeddings
        self._cos_sim = util.cos_sim
        self._model = model

    def answer(self, question):
        # Serialize initialization, inference, and cache mutations per process.
        with self._lock:
            cached = self._cache.get(question)
            if cached is not None:
                return cached
            self._initialize()
            scores = self._cos_sim(
                self._embeddings, self._model.encode(question)
            ).flatten()
            index = scores.argmax().item()
            if scores[index].item() < MIN_SIMILARITY:
                raise NoAnswerFound()
            result = self._qa_model(
                question=question, context=self._passages[index],
                handle_impossible_answer=True,
            )
            answer = result["answer"].strip()
            if not answer:
                raise NoAnswerFound()
            self._cache.put(question, answer)
            return answer
