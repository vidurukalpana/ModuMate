# Backend (Flask)

See the [backend change history](change-history/README.md) for what the original
prototype did, what each improvement added, and the before/after evaluation results.

## Prerequisites

- Python 3.14 (standard CPython).
- VS Code with the Microsoft Python extension.
- Internet access for installing dependencies and downloading models on first startup.

The existing Python 3.14.6 environment passes dependency checks, regression tests,
and a model-loading/request smoke test using locally cached models. A fresh
installation and Docker build have not been verified.

## Set up locally (macOS / Linux)

Open the repository root in VS Code, then open a terminal:

```bash
cd code/backend
python3.14 --version
```

If `.venv` already exists from an older Python installation, deactivate it if
active (`deactivate`), then rename it to an unused backup name such as
`.venv-backup`. Virtual environments must be recreated to change Python versions.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

In VS Code, run **Python: Select Interpreter** from the Command Palette and select
`code/backend/.venv/bin/python`. Confirm `python --version` reports Python 3.14.

## Run the app

From `code/backend`, with the virtual environment activated:

```bash
python app.py
```

The development backend runs on `http://localhost:5000`. The first valid question request loads
`all-MiniLM-L6-v2`, `twmkn9/bert-base-uncased-squad2`, and the bundled Excel dataset.
The first question can take several minutes while model files download. No API
keys or database configuration are required.

In another terminal, check the health endpoint (HTTP 200 with an empty body):

```bash
curl -i http://localhost:5000/health
```

Test the question endpoint:

```bash
curl -X POST http://localhost:5000/api \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is cache coherence?","category":"MP"}'
```

Only the `MP` category is supported. The root `/` has no route, so a 404 there is
expected. Stop the server with Ctrl+C.

For later sessions, activate `.venv` again and run `python app.py`.

## Docker

From `code/backend`:

```bash
docker compose up --build
```

The Docker image also uses Python 3.14 and exposes port 5000. Rebuild after code changes.

## API behavior

`POST /api` requires a JSON object with a non-empty string `question` (up to
2,000 characters after trimming) and `category: "MP"`. Request bodies are limited
to 16 KiB. Successful responses retain the shape `{"answer": "..."}`.
All errors use `{"error": "..."}`:

| Status | Meaning |
| --- | --- |
| 400 | Malformed JSON, invalid question, or unsupported category |
| 413 | Request body exceeds 16 KiB |
| 415 | Content-Type is not JSON |
| 422 | No relevant course passage or extractable answer found |
| 503 | Model or dataset initialization failed; a later request retries |
| 500 | Unexpected failure; details are logged only on the server |

The former simulated external API fallback has been removed. The backend never
returns fabricated `API response - N` answers. Clients should display the `error`
message on unsuccessful requests, including 422.

`GET /health` is a liveness check, not a model-readiness check. It remains fast
and does not download models. Models initialize once per process on demand.
The service reads complete passages and caches up to 100 exact question–response entries per process using LFU
eviction. The cache is in memory and resets when the process restarts.

## Code organization and tests

- `app.py`: application factory, CORS, request size limit, JSON error handlers.
- `controllers/`: HTTP routes and input validation.
- `services/question_answering.py`: model loading, candidate ranking, inference, diagnostics.
- `services/retrieval.py`: spreadsheet validation, source-linked chunks, bounded QA context.
- `utilities/cache_lfu.py`: small model-independent answer cache.
- `tests/`: regression tests using substitute models; no downloads required.

Run from `code/backend` with the virtual environment activated:

```bash
python -m unittest discover -s tests -v
```

`python app.py` and Docker use Flask's development server with debugging disabled.
For explicit local debugging, use `flask --app app:create_app run --debug`.
A production deployment should use a production WSGI server; each worker loads
its own models and cache. Inference is serialized within each worker.

Model answers are extracted from retrieved course passages and may be incorrect.
The smoke test verifies execution and response handling, not answer accuracy.

## Answer-quality evaluation

A 31-question Computer Architecture evaluation set covers the supplied
multiprocessor materials, with source quotations, reference answers, paraphrases,
comparisons, ambiguous prompts, and unsupported questions. Run it from this folder:

```bash
python -m evaluation.run --validate-only
python -m evaluation.run
```

See [evaluation/README.md](evaluation/README.md) for scoring, baseline results,
manual review guidance, and model-free evaluation tests.

## Multi-chunk retrieval

The backend still uses `Multiprocessors.xlsx` and the original text files. It now
reads `Sub Topic` as well as `Summary` and `File Name`; `ID` remains unused.
Paragraphs become searchable chunks. Long paragraphs use 80-word windows with
20 words of overlap. The topic name is included in each chunk's embedding.

For each question, retrieval compares both chunk embeddings and summary embeddings.
Each chunk receives the higher of its own similarity and its parent summary's
similarity; ties prefer the direct chunk score. Up to three distinct chunks are
considered, and only candidates meeting the existing 0.5 threshold reach QA.
These are prototype defaults, not calibrated probabilities.

QA receives neighboring source text, not just an isolated search paragraph:
files up to 240 words remain whole; longer files use the matched chunk and adjacent
chunks within that budget. Repeated identical contexts are evaluated once per
question. The non-empty answer with the highest QA score is returned. This score
ranks candidates; there is no new answer-confidence acceptance threshold.

The API response shape and 100-entry exact-question cache are unchanged. No course
files, evaluation questions, or models were changed. There is no external LLM call.
Uncached questions may require up to three QA calls, increasing latency.

Evaluation reports now include retrieval diagnostics: candidate source/topic,
chunk index, summary/chunk similarities, QA scores and answers, selected candidate,
and an outcome distinguishing retrieval rejection from an empty QA answer.
Diagnostics are context-local and included in evaluation reports, not API responses.

Run a comparison with:

```bash
python -m evaluation.run --output evaluation/reports/multi-chunk.json
```

The saved `evaluation/baselines/multi-chunk.json` run improved exact matches from
11/24 to 14/24 (45.8% to 58.3%) and token F1 from 46.2% to 58.7%. Answerable
questions declined fell from 12 to 9, all four unsupported questions were still
declined, and there were no operational failures. No previously exact-matching
answer regressed in this run. Comparison synthesis and clarification remain
limitations. This is a development-set result, not held-out accuracy.
