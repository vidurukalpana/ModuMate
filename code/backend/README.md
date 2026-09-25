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
| 200 | Accepted local answer or explicitly labelled simulated fallback |
| 503 | Model or dataset initialization failed; a later request retries |
| 500 | Unexpected failure; details are logged only on the server |

When retrieval or QA cannot provide an accepted local answer, the API returns a
simulated fallback with HTTP 200 and an `answer` string, plus
`source: "simulated_fallback"` and `simulated: true`. This is a placeholder for a
future LLM integration and is not cached. Invalid requests and operational failures
still return their documented error statuses.

`GET /health` is a liveness check, not a model-readiness check. It remains fast
and does not download models. Models initialize once per process on demand.
The service reads complete passages and caches up to 10 exact question–response entries per process using LFU
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
These are prototype defaults, not calibrated probabilities. The confidence
policy can override the retrieval threshold for a service instance.

QA receives neighboring source text, not just an isolated search paragraph:
files up to 240 words remain whole; longer files use the matched chunk and adjacent
chunks within that budget. Repeated identical contexts are evaluated once per
question. Among candidates passing the confidence policy, the answer with the highest QA
score is returned. See the answer-confidence section below for acceptance rules.

The API response shape and 10-entry exact-question cache are unchanged. No course
files, evaluation questions, or models were changed. The default uses simulation; an optional Ollama fallback can be enabled.
Uncached questions may require up to three QA calls, increasing latency.

Evaluation reports now include retrieval diagnostics: candidate source/topic,
chunk index, summary/chunk similarities, QA scores and answers, selected candidate,
and an outcome distinguishing retrieval rejection from an empty QA answer.
Diagnostics are context-local and included in evaluation reports, not API responses.

Run a comparison with:

```bash
python -m evaluation.run --output evaluation/reports/multi-chunk.json
```

## Answer-confidence checks

Each candidate must pass two separate checks: retrieval relevance (default 0.5)
and QA score (default 0.5). The answer must also be non-empty and occur in the
provided source context after whitespace normalization. Invalid numeric scores
are rejected. A high score attached to an empty QA answer remains a refusal.
These checks are filtering rules, not proof of correctness or calibrated odds.

Only accepted local QA answers and validated, cited LLM answers are cached. If all eligible candidates are rejected, the
API returns the labelled simulated fallback with HTTP 200. Accepted local
answers retain the existing `{"answer": "..."}` shape.
Evaluation diagnostics include the policy, each candidate's `accepted` flag and
`rejection_reason`, and `no_candidate_passed_confidence` when non-empty candidates
fail the checks. The default cache is 10 exact questions per process.

The policy is immutable for a service instance. To configure the application in
Python, inject a new service (and therefore a fresh cache):

```python
from app import create_app
from services.confidence import ConfidencePolicy
from services.question_answering import QuestionAnsweringService

app = create_app(QuestionAnsweringService(
    confidence_policy=ConfidencePolicy(min_retrieval_score=0.5, min_qa_score=0.5)
))
```

For evaluation, pass explicit thresholds without changing application defaults:

```bash
python -m evaluation.run --min-retrieval-score 0.5 --min-qa-score 0.5
python -m evaluation.confidence_sweep evaluation/baselines/answer-confidence.json
```

The QA cutoff is now 0.5 by explicit prototype routing choice. The earlier 0.15
experiment and its results remain in the historical reports. Neither cutoff is a
calibrated correctness probability. Below-threshold or empty answers route to the
simulator; no external network call, API key, or Ollama installation is required.
A score exactly equal to 0.5 passes the gate. Restart the backend to use the new
policy and clear its in-memory cache.

The simulator returns:

```json
{
  "answer": "Simulated external LLM response: no accepted local answer was found. A real LLM is not connected yet.",
  "source": "simulated_fallback",
  "simulated": true,
  "fallback_reason": "low_qa_score"
}
```

## Inspecting local answers and fallback routing

Run `python -m evaluation.run` from this folder and open
`evaluation/reports/latest.json`. The summary now separates:

- `local_answer_count`: responses containing real local answers, excluding placeholders.
- `local_answer_exact_match_rate`: exact matches divided by all locally served
  answers. Answers to unsupported or ambiguous cases count as non-matches.
- `simulated_fallback_rate`: simulated fallback responses divided by all cases.
- `answer_exact_match`: the existing score over all answerable cases, including
  those routed to fallback as zero-credit cases.

Rates are `null` when their denominator is zero. These are lexical evaluation
metrics, not guarantees of correctness or completeness.

Simulated responses now include a stable `fallback_reason`:

| Reason | Meaning |
| --- | --- |
| `low_retrieval_score` | No candidate reached the retrieval threshold |
| `low_qa_score` | Non-empty candidates failed the QA score threshold |
| `no_extracted_answer` | All eligible QA contexts produced empty answers |
| `invalid_retrieval_score` | Retrieval produced a non-finite or out-of-range score |
| `invalid_qa_score` | Non-empty candidates had invalid QA scores |
| `answer_not_in_context` | Non-empty candidates failed source-span checks |
| `no_accepted_answer` | Mixed rejection reasons or no specific reason available |

If some candidates are empty and others fail a check, the reason describes the
non-empty candidates. Full per-candidate decisions remain in `retrieval` diagnostics.
The frontend can keep displaying `answer` and optionally use the reason for routing
or debugging. The optional Ollama provider now uses this boundary; see [Ollama setup](LLM_SETUP.md).
Input errors, initialization failures, and unexpected exceptions retain error
responses; they do not become fake answers.

## Optional real LLM fallback

See [LLM_SETUP.md](LLM_SETUP.md) for installation, configuration, request/response
behavior, failure codes, Docker networking, and evaluation. Set
`LLM_FALLBACK_MODE=ollama` and `OLLAMA_MODEL` to an installed model name to enable
it. The default is still `simulated`. Both local acceptance thresholds remain 0.5.
Ollama answers include source citations and provider metadata; provider failures
return 502/503/504 rather than fake responses. Validated, cited LLM answers now share the 10-entry cache with local QA.

## Local environment file

`code/backend/.env` is now loaded automatically by the application and evaluation
runner via `python-dotenv`. Use `.env.example` as a template; exported environment
variables take precedence. Restart after changes. The repository-root `.gitignore`
already ignores `.env` and `.env.*` while allowing `.env.example`.
See [the setup guide](LLM_SETUP.md) for an Ollama configuration example.

## Shared response cache

The API now checks one LFU cache before QA or Ollama. It holds **10 responses total**
per application process, keyed by category and exact question after trimming outer
whitespace. Accepted QA answers and validated, cited LLM answers share those slots.
Provider/model metadata and citations are preserved. Every successful API response
includes `cache_hit`: false when freshly processed, true when reused. `source`
describes original answer provenance, not whether this request contacted Ollama.

The cache resets on restart. Restart after changing models, thresholds, or course
files. Access is synchronized; simultaneous cache misses can still issue duplicate
provider requests. Cached responses are copied to prevent client-side mutation of
stored citations. Cache lookup is outside the QA inference lock, so a hit does not
wait for another question's model inference.

## Unsupported and ambiguous questions

- Unspecified comparisons: “This question does not identify the systems being compared.”
- Other missing subjects: “This question does not identify the architecture, operation, or protocol being discussed.”
- Missing course evidence: a standalone explanation that the supplied notes cannot support the answer.

These are HTTP 200 responses with `answer`, `abstained: true`, and `cache_hit: false`.
Policy responses retain their `reason`, `source: question_policy`, and suggested
topics. They are not cached. Explicit missing-subject and named-entity checks run
before models; relevance below 0.20 after retrieval rejection avoids fallback.
Borderline supported questions still reach the notes-only LLM. Both original
acceptance thresholds remain 0.5. English heuristics may miss paraphrases or casing
variants; the relevance floor is provisional, not a semantic correctness guarantee.

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

Q&A confidence must be **strictly greater than 0.5**. A score of exactly 0.5
is rejected and follows the fallback path. Non-empty and source-span checks also apply.

## Answer source attribution

Every successful `/api` response includes `answer`, `source`, `sources`, and
`cache_hit`. `source` is `local_qa`, `llm_fallback`, `simulated_fallback`, or
`question_policy`. It describes the original answer path, independently of caching.

An illustrative local response:

```json
{
  "answer": "Single Instruction Stream, Single Data Stream",
  "source": "local_qa",
  "cache_hit": false,
  "sources": [{
    "id": "S1",
    "source": "Files/course.txt",
    "topic": "Flynn's classification",
    "chunk_index": 0,
    "excerpt": "SISD means Single Instruction Stream, Single Data Stream."
  }]
}
```

The example filename and excerpt illustrate the format, not a recorded result.
Source paths are relative to `text_files`; absolute paths are never public citations.
Chunk indices are zero-based within a file and identify the retrieved chunk.
The excerpt is the actual model context and can include neighboring chunks.
Ollama excerpts reflect the text after context truncation. IDs such as `S1` are
response-local references, not permanent document identifiers.

Accepted local answers include their selected source. Ollama returns only cited
sources from the excerpts supplied in that request, with duplicate IDs removed.
Cached answers preserve all original attribution and set `cache_hit: true`.
Policy limitations, Ollama abstentions, and simulated placeholders have `sources: []`.
Citations permit inspection; they do not prove every generated claim is supported.
The Q&A confidence requirement remains strictly greater than 0.5; cache capacity is 10.
Restart the backend after updating code or notes to clear old in-memory entries.

## Cache configuration and metrics

Set `CACHE_CAPACITY=10` in the backend `.env` and restart Flask. The default is
10 entries. Exported environment values take precedence. Invalid or non-positive
integer settings fail startup. Configuration is per process, not a shared cache.

```bash
curl -sS http://localhost:8000/cache/stats | python3 -m json.tool
```

The endpoint returns `capacity`, `entries`, `hits`, `misses`, `hit_rate`, `inserts`,
`updates`, and `evictions`. Hit rate is hits divided by lookups, or zero before any
lookup. Inserts count new entries; updates count replacements of existing keys;
evictions count removals caused by capacity pressure. Reading statistics changes
no counters. The endpoint reveals no questions, answers, sources, or excerpts.

All production lookups, writes, and snapshots use the same cache lock. Invalid
requests and policy decisions made before lookup do not count as misses. A miss
counts even when the later answer abstains or fails. Concurrent misses can still
compute the same answer; this change does not coalesce model calls.
Counters and entries reset at restart, and each server worker has independent
statistics. LFU eviction and oldest-insertion tie-breaking remain unchanged.

## Semantic cache (opt-in)

```ini
SEMANTIC_CACHE_ENABLED=false
SEMANTIC_CACHE_THRESHOLD=0.90
```

Set the flag to `true` and restart to enable it. The flag accepts true/false;
the threshold must be finite and in (0, 1]. The default is deliberately disabled
pending validation on your workload. This threshold is unrelated to QA score > 0.5.

Exact matching runs first without embedding work. On a miss, same-category cached
questions are eligible only when conservative intent and subject checks agree.
Currently supported forms are acronym expansion ("What does SISD stand for?" /
"What is the full form of SISD?"), definitions ("What is X?" / "Define X"), and
listing advantages or disadvantages. All subject words and ordering must match;
unknown forms miss safely. Similarity alone cannot override these checks.

Eligible questions are encoded in a batch using the existing MiniLM instance under
its inference lock. The best eligible match at or above the configured threshold
is reused. Only the original cache entry is retained, with its LFU frequency
incremented; paraphrases do not create aliases or consume extra entries. Entries
are rechecked after embedding work so evicted/replaced answers cannot be returned.
For this small cache, vectors are recomputed for eligible candidates rather than
maintaining a separate index. Semantic lookup therefore has a measurable cost.

Hits include `cache_match_type: exact` or `semantic`; semantic hits also include
`cache_similarity`. Original answer sources/excerpts/provider metadata are preserved.
No guessed confidence is attached to the answer. `/cache/stats` separates
`exact_hits` and `semantic_hits`; `hits` is their sum, and `misses` counts requests
not served by either lookup. A semantic hit converts its initial exact miss into
a hit. Metrics and entries remain process-local and reset on restart.

## Cache invalidation

`CACHE_TTL_SECONDS=3600` gives answers a one-hour fixed lifetime from insertion.
Use any positive finite seconds value and restart after configuration changes.
Hits do not extend expiry. Expired entries are removed lazily during lookup,
insertion, statistics reads, or candidate selection, including semantic lookup.

Before each answer request the backend hashes the spreadsheet and course text
contents. Changes invalidate the entire answer cache and reset retrieval/model
initialization plus policy vocabulary together. The next inference rebuilds the
index. Active model IDs, confidence/retrieval settings, fallback configuration,
prompt, and semantic settings also participate in version checking. This is a
small-course implementation: hashing all files costs I/O per request, and a data
change reloads models as well as embeddings. There is no background watcher.
Unreadable required files fail closed with 503 rather than returning cached text.
Environment edits require restart; `.env` is not a hot-reload interface. Replacing
weights behind the same Ollama model name is not detected; restart after doing so.

To enable manual clearing, set a private `CACHE_ADMIN_TOKEN` in `.env` and restart.
`POST /cache/clear` requires `Authorization: Bearer <your-token>` and returns
`{"removed": 3}` (the count varies). Missing/wrong credentials return 401; an empty
configured token disables the operation with 403. No cache content is returned.
For example, with the same token exported in your testing shell:

```bash
curl -sS -X POST http://localhost:8000/cache/clear \
  -H "Authorization: Bearer $CACHE_ADMIN_TOKEN"
```

Clears increment a generation counter. A request already computing an answer may
finish for its caller, but cannot repopulate a cache cleared in the meantime.
Changes found at the end of computation also prevent that result being cached.
Manual clearing leaves the retrieval index intact; material changes reset it.

Statistics add `ttl_seconds`, `expirations` (entries), `invalidations` (events),
`invalidated_entries`, and `invalidation_reasons` (event counts). Reasons include
manual, materials_changed, configuration_changed, and materials_unavailable.
These are separate from capacity evictions. Clears preserve counters; process
restart resets them. Each worker has an independent cache: manual clearing affects
only the worker handling that request, while each detects files on its next request.

## Backend observability

Every HTTP response includes an internally generated `X-Request-ID`. Incoming IDs
are not trusted or reused. Application completion logs contain a JSON object with
the ID, route template (not raw URL), method, status, duration, answer origin,
cache match type, fallback/policy reason, abstention, actual provider-call count,
error category, and stage durations. No request bodies, answer text, excerpts,
authorization headers, raw exception messages, or raw query strings are logged
by these hooks. Third-party/server logs have their own logging behavior.

Stages cover cache-version checking, exact lookup, semantic matching/encoding,
initial model loading, retrieval, extractive inference, and Ollama HTTP. Timings
use a monotonic performance clock and are recorded even when a stage raises.
Nested timings overlap and must not be summed into total latency. Multiple QA
candidates accumulate into one per-request stage duration. Lock waiting can appear
in the enclosing stage/request duration. Ollama timing measures transport and body
reading; it does not include preceding QA or subsequent response validation.

`GET /health` remains an empty 200 liveness check. `GET /ready` returns 200 when
local retrieval/models are initialized, otherwise 503 (including cold startup
and after invalidation). It does not initialize anything, reread course files, or
contact Ollama. `ollama: not_checked` is explicit: readiness is not a provider probe.
A cold backend may accept its first question while reporting not ready.

Set a private `METRICS_TOKEN` in `.env` and restart to enable `GET /metrics`:

```bash
curl -sS http://localhost:8000/metrics \
  -H "Authorization: Bearer $METRICS_TOKEN" | python3 -m json.tool
```

Export the token in the testing shell to use that command. Missing/wrong tokens
return 401; an unset configured token disables access with 403. The JSON snapshot
contains aggregate counts, lifetime mean timings, and recent p95 timings based on
at most 256 samples per fixed timing group. Collection is synchronized, bounded,
and process-local. No individual requests or IDs are retained in metrics.

Origin counts include cached answers; `provider_calls` counts actual attempted
Ollama HTTP calls, including failures. Response timing groups distinguish exact
and semantic hits from local answers, LLM fallbacks, simulations, and policy
responses. Counters also cover statuses, error categories, routes and reasons.
All endpoints, including readiness and metrics requests, contribute to counters;
a metrics response reflects completed requests before that scrape finishes.
Metrics remain collected when access is disabled. Restart resets them; multiple
workers have separate snapshots. This is JSON observability, not a Prometheus
exporter or distributed tracing system. Answer/cache behavior is unchanged.
