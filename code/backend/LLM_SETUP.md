# Optional Ollama fallback

The default remains `simulated`, so existing local runs need no new installation.
Set `LLM_FALLBACK_MODE=ollama` to make real calls to a separately running Ollama
server. No cloud API key is needed for a downloaded local model. Ollama is not
bundled with this repository and model downloads can be large.

## Local setup

1. Install Ollama using its [official instructions](https://docs.ollama.com/quickstart).
2. Download a model suitable for your machine with `ollama pull MODEL_NAME`.
   Use a local model with chat and structured-output support. Choose its size
   based on available memory; this implementation does not prescribe a model.
3. Start Ollama (the desktop app or `ollama serve`), then run `ollama list` to
   confirm the exact installed model name.
4. From `code/backend`, configure and launch Flask:

```bash
source .venv/bin/activate
export LLM_FALLBACK_MODE=ollama
export OLLAMA_MODEL='YOUR_INSTALLED_MODEL_NAME'
export OLLAMA_BASE_URL='http://localhost:11434'
export OLLAMA_TIMEOUT_SECONDS=60
python app.py
```

Replace `YOUR_INSTALLED_MODEL_NAME` with the exact name shown by `ollama list`.
These settings can also be placed in `code/backend/.env` without `export`.
The backend and evaluation runner automatically load that file. Exported variables
take precedence. Restart the process after changing settings.
A missing model name, unsupported mode, invalid URL, or invalid timeout fails at
startup rather than silently using fake answers.

Test a question that the current QA model routes to fallback:

```bash
curl -X POST http://localhost:5000/api \
  -H 'Content-Type: application/json' \
  -d '{"question":"What does SISD stand for?","category":"MP"}'
```

A generated response includes `answer`, `source: "llm_fallback"`, `provider:
"ollama"`, `model`, `simulated: false`, `fallback_reason`, and cited `sources`.
A local QA answer still uses the original `{"answer": "..."}` response.

Return to the simulator with `export LLM_FALLBACK_MODE=simulated` and restart Flask.

## Routing and source grounding

The local QA threshold stays 0.5, and the retrieval threshold stays 0.5. A cache
hit or accepted QA answer bypasses Ollama. On a retrieval/QA rejection, the service
passes up to three retrieved contexts, with source filenames and topic names,
to the fallback. Even below-threshold candidates are provided as potentially
irrelevant evidence, allowing the LLM to assess borderline retrieval matches.
The prompt explicitly allows abstention when those excerpts cannot support an answer.

Context is deduplicated and limited to 12,000 characters. No evaluation references
are sent. The `/api/chat` call disables streaming and requests a JSON schema with
`answer` or `abstain` status, text, and source IDs. Answer citations must
reference supplied excerpts. Citation validation checks membership, not whether
an answer logically follows from its source. Human answer-quality review remains
necessary; model instructions alone cannot guarantee grounding.

The simulator is never silently substituted for a failed real provider. Model
initialization failures still return 503. Raw provider errors are not exposed.
The timeout bounds blocking socket operations, not total wall-clock duration of
all operations; there are no automatic retries. Responses are limited to 1 MiB,
answer text to 8,000 characters, and generation to 768 output tokens.

## Evaluation and tests

```bash
# Real model evaluation: requires a running Ollama server and configured model.
python -m evaluation.run --fallback-mode ollama --output evaluation/reports/ollama.json

# Original simulated routing comparison; no Ollama calls.
python -m evaluation.run --fallback-mode simulated --output evaluation/reports/simulated.json

# Provider tests use controlled responses, no network or model downloads.
LLM_FALLBACK_MODE=simulated python -m unittest discover -s tests -v
```

## Docker

Compose forwards `LLM_FALLBACK_MODE`, `OLLAMA_MODEL`, `OLLAMA_BASE_URL`, and
`OLLAMA_TIMEOUT_SECONDS`. On Docker Desktop for macOS, use
`OLLAMA_BASE_URL=http://host.docker.internal:11434` to reach the host server;
`localhost` inside the container points to the container itself. Host/network
reachability still depends on the Ollama listener configuration. Rebuild the
backend image after code changes. No Ollama container is installed automatically.

## Verification limits

The integration was tested using controlled HTTP responses and the existing
real QA models in simulated mode. Ollama was not available on the development
machine's command path, so no real Ollama answer-quality result is claimed.

## Automatic .env loading

Install updated dependencies once: `python -m pip install -r requirements.txt`.
Copy `.env.example` to `.env` if you do not already have a local file, then edit it:

```dotenv
LLM_FALLBACK_MODE=ollama
OLLAMA_MODEL=llama3.2:1b
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TIMEOUT_SECONDS=120
```

Run `python app.py` or `python -m evaluation.run` normally; no `source .env` is
needed. The path is resolved relative to the backend directory. Existing exported
settings win over .env values; unset an old export if you want the file to control
it. Evaluation CLI options take precedence over both where supported.

The repository-root `.gitignore` already contains `.env`, `.env.*`, and
`!.env.example`. These rules ignore local .env files at any depth while allowing
the example template. Do not add a duplicate rule to the backend ignore file.
Check with `git check-ignore -v code/backend/.env` from the repository root.
An ignore rule does not untrack files already committed; remove such a file from
Git's index before committing future changes, and rotate any exposed credentials.

## Notes-only response policy

The backend returns supported answers or standalone limitation statements.
Ambiguous comparisons return: “This question does not identify the systems being compared.”
Questions without supporting material receive an insufficient-evidence statement.
Only supported answers are cached. The Ollama schema accepts `answer` and `abstain`;
other status values are rejected as invalid provider responses.

The evaluation uses `evaluation/cases.json` (version 2), containing the same 31
questions and 24 reference-answer sets. The three ambiguous cases and four
unsupported cases expect abstention. Earlier baseline reports retain their
original measurements and expectations; they are historical records.
