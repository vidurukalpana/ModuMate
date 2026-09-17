# Backend (Flask)

## Prerequisites

- Python 3.14 (standard CPython).
- VS Code with the Microsoft Python extension.
- Internet access for installing dependencies and downloading models on first startup.

The dependency pins have been updated for the Python 3.14 migration. A full
installation and model-loading smoke test is still required before considering
the migration verified.

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

The development backend runs on `http://localhost:5000`. Startup loads
`all-MiniLM-L6-v2`, `twmkn9/bert-base-uncased-squad2`, and the bundled Excel dataset.
The first startup can take several minutes while model files download. No API
keys or database configuration are required.

In another terminal, check the health endpoint (HTTP 200 with an empty body):

```bash
curl -i http://localhost:5000/health
```

Test the question endpoint:

```bash
curl -X POST http://localhost:5000/api \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is a multiprocessor?","category":"MP"}'
```

Only the `MP` category is supported. The root `/` has no route, so a 404 there is
expected. Stop the server with Ctrl+C.

For later sessions, activate `.venv` again and run `python app.py`.

## Docker

From `code/backend`:

```bash
docker compose up --build
```

The Docker image also uses Python 3.14 and exposes port 5000.
