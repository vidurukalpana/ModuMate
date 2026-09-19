# Backend (Flask)

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
- `services/question_answering.py`: dataset validation, model loading, retrieval, inference.
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
