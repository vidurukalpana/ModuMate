"""Source-linked chunks for the small, in-memory course search index."""

from dataclasses import dataclass
from pathlib import Path
import re

CHUNK_WORDS = 80
CHUNK_OVERLAP = 20
TOP_K = 3
CONTEXT_WORDS = 240


@dataclass(frozen=True)
class PassageChunk:
    source: str
    topic: str
    text: str
    index: int
    context: str = ""


def split_passage(text, max_words=CHUNK_WORDS, overlap=CHUNK_OVERLAP):
    """Search paragraphs separately and split long ones into overlapping windows."""
    if max_words < 1 or not 0 <= overlap < max_words:
        raise ValueError('Require max_words > overlap >= 0')
    for paragraph in re.split(r'\n\s*\n', text.strip()):
        words = paragraph.split()
        for start in range(0, len(words), max_words - overlap):
            yield ' '.join(words[start:start + max_words])
            if start + max_words >= len(words):
                break


def load_course(data_directory):
    """Load spreadsheet metadata and validate every linked course passage."""
    import pandas as pd

    data_directory = Path(data_directory)
    dataset = pd.read_excel(data_directory / 'Multiprocessors.xlsx')
    columns = ['Sub Topic', 'Summary', 'File Name']
    if dataset.empty or not set(columns).issubset(dataset.columns):
        raise ValueError('Course dataset is empty or missing required columns')
    records = []
    directory = (data_directory / 'Files').resolve()
    for topic, summary, filename in dataset[columns].itertuples(index=False, name=None):
        if any(not isinstance(value, str) or not value.strip() for value in (topic, summary, filename)):
            raise ValueError('Course topic, summary and filename must be non-empty strings')
        path = (directory / f'{filename}.txt').resolve()
        if path.parent != directory:
            raise ValueError('Course passage must be inside the Files directory')
        passage = path.read_text(encoding='utf-8').strip()
        if not passage:
            raise ValueError('Course passage is empty')
        records.append((topic.strip(), summary, str(Path('Files') / path.name), passage))
    return records


def build_chunks(records):
    chunks, owners = [], []
    for row, (topic, _, source, passage) in enumerate(records):
        texts = list(split_passage(passage))
        for index, text in enumerate(texts):
            # Search focused evidence, but give QA its neighboring context.
            if len(passage.split()) <= CONTEXT_WORDS:
                context = passage
            else:
                neighbors = [text]
                remaining = CONTEXT_WORDS - len(text.split())
                for neighbor in (index - 1, index + 1):
                    if 0 <= neighbor < len(texts) and len(texts[neighbor].split()) <= remaining:
                        remaining -= len(texts[neighbor].split())
                        if neighbor < index:
                            neighbors.insert(0, texts[neighbor])
                        else:
                            neighbors.append(texts[neighbor])
                context = "\n\n".join(neighbors)
            chunks.append(PassageChunk(source, topic, text, index, context))
            owners.append(row)
    return chunks, owners
