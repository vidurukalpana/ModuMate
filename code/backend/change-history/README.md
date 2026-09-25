# Backend change history

This document explains how the backend has changed from the original prototype.
Entries are ordered from oldest to newest. Branch names identify where work was
performed; they do not imply a change has been committed or merged.

For setup and current behavior, see the [backend README](../README.md).
For evaluation details, see the [evaluation guide](../evaluation/README.md).

## 1. Backend refactoring and error handling

Recorded: 2026-09-19. Branch was not recorded for this change.

| Area | Before | Improved / added |
| --- | --- | --- |
| Organization | HTTP handling, retrieval, model calls, and fallback logic lived in the API controller. | Application factory, route validation, question-answering service, and separate cache utility. |
| Model loading | Models loaded at import time; the cache also loaded its own embedding model. | Models initialize lazily once per service instance on the first valid question; duplicate cache model removed. |
| Passage reading | Only the first line of the selected text file reached QA. | Complete passage content became available to QA. |
| Request validation | Missing or invalid fields could reach model code and cause exceptions. | Validate JSON objects, non-empty questions, the MP category, a 2,000-character question limit, and a 16 KiB request limit. |
| Error responses | Unexpected exceptions returned HTTP 400 with raw exception text. | Consistent JSON errors, appropriate HTTP statuses, and server-side logging of internal failures. |
| Fallback | Simulated an external API using a delay, counter, and fake `API response - N` text. | Removed the simulation; unsupported/no-answer requests return HTTP 422. |
| Cache matching | Similarity-based lookup with four initially empty DataFrame entries; cached simulated fallback responses. | Exact-question LFU cache storing actual successful answers; no pandas or embedding model needed inside the cache. |
| Development setup | Debug mode enabled in `app.py`; obsolete Compose configuration and a development bind mount. | Debug mode disabled by default and Compose simplified. |
| Verification | No backend regression suite. | 11 regression tests, dependency check, and cached-model smoke test. |

**API impact:** `/api` and `/health` remain. Successful responses still use
`{"answer": "..."}`. Errors use `{"error": "..."}`. Clients must handle
400, 413, 415, 422, 500, and 503 responses. `/health` checks process liveness;
it does not initialize or verify the models.

**Limitations:** no real external LLM, semantic cache lookup, or model-readiness
endpoint. Model answer quality was not solved by this refactor.

## 2. Cache capacity increase

Recorded: 2026-09-19. Branch was not recorded for this change.

| Before | Improved / added |
| --- | --- |
| Up to four exact question–response entries after the refactor. | Up to 100 entries per backend process. |

LFU eviction remains: replace the least-used entry when full; ties evict the
oldest inserted entry. Entries are held in memory and disappear on restart.
Capacity is a constructor default, not an environment setting. Cache hits still
require an exact question match after the API trims surrounding whitespace.

**Verification:** all 11 existing tests passed. This was a capacity change, not
an experimentally established ideal cache size; hit/miss metrics remain future work.

## 3. Source-grounded answer-quality evaluation

Recorded: 2026-09-19.
Branch: `feature/test/answer-quality-evaluation-set`.

| Before | Improved / added |
| --- | --- |
| Regression tests checked code behavior, but no repeatable course-answer benchmark existed. | Added `evaluation/cases.json` and a runner exercising the API through Flask's test client. |
| Answer quality was checked with a few manual questions. | 31 cases: 19 direct, 3 paraphrased, 2 comparison, 3 ambiguous, and 4 unsupported questions. |
| No stored expected answers or supporting evidence for quality checks. | 24 answerable cases include reference answers and exact quotes covering all 11 course text files; seven cases specify clarification or abstention. |
| No baseline quality report. | Saved per-question responses, text-match metrics, behavior metrics, timings, package versions, and dataset/source hashes. |

**Data impact:** new testing material only. The original spreadsheet and course
text files were not changed. The dataset is not supplied to the model as an answer
lookup table and does not train or fine-tune either model.

**Baseline:** [initial.json](../evaluation/baselines/initial.json).

- Exact match: 11/24 (45.8%). Token F1: 46.2%.
- Answerable questions declined: 12/24; one returned comparison answer was incomplete.
- Unsupported questions declined: 4/4. Clarification requests: 0/3.
- Operational errors: 0. All 17 regression and evaluation tests passed.

**Interpretation:** exact match and token F1 are lexical measures, not guaranteed
correctness. Comparison answers need human review. This is a small development
set, not a held-out test of general Computer Architecture knowledge.

## 4. Multi-chunk retrieval and failure diagnostics

Recorded: 2026-09-19.
Branch: `feature/improve-multi-chunk-retrieval`.

| Area | Before | Improved / added |
| --- | --- | --- |
| Search target | Compared the question against spreadsheet summaries only. | Searches topic-labelled text chunks as well as summaries. |
| Spreadsheet fields | Used `Summary` and `File Name`. | Also uses `Sub Topic`; `ID` remains unused. |
| Chunking | One full passage associated with each summary. | Paragraph chunks; long paragraphs split into 80-word windows with 20-word overlap. |
| Candidate selection | Selected one passage. | Considers up to three distinct chunks using the higher of chunk or parent-summary similarity; direct chunk similarity breaks ties. |
| QA context | One selected full passage. | Whole source for files up to 240 words, otherwise the selected chunk plus nearby chunks within a 240-word budget. |
| Answer selection | Used one QA result. | Chooses the highest-scoring non-empty answer among eligible candidates; identical contexts are evaluated once. |
| Failure visibility | Reports recorded only the final response. | Reports include candidate sources, topics, chunk indexes, similarities, QA scores, selected answer, and a distinct failure reason. |

**Unchanged:** the retrieval threshold remains 0.5. The models, course content,
evaluation questions, public API format, and 100-entry exact cache remain the same.
QA score ranks candidates; a calibrated answer-confidence acceptance threshold has
not been added. No LLM fallback was introduced.

**Verification:** all 25 tests passed. The real-model evaluation used the same case
and source hashes as the original baseline. Report:
[multi-chunk.json](../evaluation/baselines/multi-chunk.json).

| Metric | Before | After |
| --- | ---: | ---: |
| Exact matches | 11/24 (45.8%) | 14/24 (58.3%) |
| Token F1 | 46.2% | 58.7% |
| Answerable questions declined | 12/24 | 9/24 |
| Unsupported questions declined | 4/4 | 4/4 |
| Clarification requests | 0/3 | 0/3 |
| Operational errors | 0 | 0 |

No previously exact-matching answer regressed in the saved run. Additional exact
matches were the SIMD expansion, MIMD expansion, and a paraphrased UMA question.

**Tradeoffs and limitations:** uncached questions can require up to three QA calls.
Comparison synthesis, clarification, and nine answerable refusals remain unresolved.
The improvement was measured on the development set used during implementation;
it is not evidence of held-out accuracy.

## 5. Answer-confidence checks

Recorded: 2026-09-19.
Branch: `feature/answer-confidence-checks`.

| Area | Before | Improved / added |
| --- | --- | --- |
| Acceptance | Any non-empty QA result could be returned once retrieval passed. | Separate immutable policy for retrieval and QA acceptance; defaults 0.5 and 0.15. |
| Source extraction | Trusted model answer text without checking it against the context. | Require the answer to occur in its QA context after whitespace normalization. This does not prove correctness. |
| Numeric validation | No explicit handling of non-finite retrieval/QA scores. | Reject invalid scores; validate configured cutoffs as finite numbers from 0 to 1. |
| Candidate selection | Picked the highest-scoring non-empty answer. | Pick the highest-scoring accepted candidate; a rejected candidate cannot hide a valid alternative. |
| Refusals and caching | Empty QA results declined; successful answers cached. | Low-confidence or unsupported-span results also decline with HTTP 422 and are never cached. |
| Diagnostics | Similarity and QA scores recorded. | Also records effective policy, acceptance flags, and explicit rejection reasons. |
| Experiments | Threshold changes required code edits. | Evaluation CLI cutoff overrides and an offline QA-cutoff sweep over recorded candidates. |

**Diagnosis:** four of nine refusals had no candidate above the retrieval cutoff;
five had eligible contexts but empty QA outputs. This does not imply every eligible
context contained the correct evidence. The incomplete comparison answer had a
QA score around 0.56, above a correct answer scoring around 0.19.

**Verification:** 33 tests passed, including cutoff boundaries, invalid scores,
source-span checks, fallback to a valid candidate, rejection/cache behavior, and
cutoff replay. The real-model [confidence baseline](../evaluation/baselines/answer-confidence.json)
retains 14/24 exact matches (58.3%), 58.7% token F1, nine answerable refusals,
four unsupported refusals, zero clarifications, and zero operational errors.
No reference questions, course materials, models, or public API shapes changed.

The [cutoff sweep](../evaluation/baselines/confidence-sweep.json) retained 58.3%
exact match at 0.15, fell to 54.2% at 0.20 and 37.5% at 0.50. All four unsupported
questions remained declined. The 0.15 default is provisional and development-set
informed, not a calibrated correctness probability.

**Limitations:** this branch adds acceptance controls but demonstrates no increase
in answer accuracy on the saved set. The incomplete comparison still passes.
Retrieval misses, empty QA outputs, comparison synthesis, and clarification remain
future work. A separate held-out set is needed to assess generalization.

## 6. Restore simulated fallback with QA cutoff 0.5

Recorded: 2026-09-19.
Branch: `feature/answer-confidence-checks`.

| Before | Improved / added |
| --- | --- |
| Default QA acceptance cutoff was 0.15. | Set to 0.5 at the user's request; retrieval cutoff also remains 0.5. Equality passes. |
| No accepted local answer returned HTTP 422. | Return HTTP 200 with an explicitly simulated external LLM placeholder in `answer`, plus `source: "simulated_fallback"` and `simulated: true`. |
| No temporary fallback provider. | Added a separate simulator function for replacement by a real provider later. No network calls, artificial delay, or API credentials. |
| Evaluation treated 422 as abstention. | Counts simulated fallbacks separately and awards no answer/abstention/clarification credit to placeholders. |

The simulator covers retrieval rejection and failed QA acceptance. Invalid inputs,
model initialization failures, and unexpected server errors retain their existing
error responses. Only accepted real local answers enter the cache; placeholders
do not. Restart the backend to apply the new policy and reset cached answers.

The earlier 0.15 results remain historical evidence, not current configuration.
A higher QA cutoff increases fallback routing and does not guarantee correctness.
Verification: 33 tests passed; see the separately saved
[simulated-fallback report](../evaluation/baselines/simulated-fallback.json) for the
real-model routing evaluation: 10 local answers, 21 simulated fallbacks, and zero
operational errors across 31 cases. Nine of the 24 answerable cases matched exactly
(37.5%); simulated responses receive no quality credit. Course data and reference
cases were unchanged.

## 7. Routing reasons and local-answer metrics

Recorded: 2026-09-19.
Branch: `feature/answer-confidence-checks`.

| Before | Improved / added |
| --- | --- |
| Simulated fallback identified itself but did not explain why it was used. | Added a stable `fallback_reason` for low retrieval/QA scores, empty extraction, invalid scores, source-span rejection, or mixed/unspecified rejection. |
| Overall exact match mixed local-answer quality with local coverage. | Added local-answer count, exact-match rate among local answers, and simulated-fallback rate. Undefined rates use null. |
| Policy-level boundary checks existed. | Added API-level tests for equality at 0.5, below-threshold routing, reason codes, and excluding placeholders from the cache. |

Unknown internal reason text is mapped to `no_accepted_answer`; mixed candidate
rejections use the same generic code. The response still includes `answer`,
`source`, and `simulated`, so existing clients can continue displaying the text.
Thresholds and inference behavior remain unchanged. Validation and operational
errors still use error responses.

Verification: 38 tests passed. The separately saved
[routing report](../evaluation/baselines/routing-diagnostics.json) records the
current model run. This is an observability and test-coverage change, not a claim
of improved model accuracy. Historical reports remain unchanged.

## 8. Optional Ollama LLM fallback

Recorded: 2026-09-23.
Branch: `feature/llm-fallback`.

| Before | Improved / added |
| --- | --- |
| Fallback only returned a fake answer and accepted a reason code. | Optional Ollama provider receives the question, category, reason, and up to three retrieved course contexts. Simulation remains the default. |
| Rejected QA contexts were unavailable to the fallback. | No-answer exceptions carry source-labelled contexts, including borderline retrieval candidates; duplicates and prompt size are bounded before sending. |
| No generated-response validation. | Structured answer/abstain/clarify outputs; answer citations must reference supplied source IDs. Empty, malformed, oversized, and truncated outputs are rejected. |
| No external service failure handling. | Configurable socket timeout, bounded response reads, safe 502/503/504 errors, no silent fake-response substitution and no automatic retries. |
| Evaluation assumed every real answer came from extractive QA. | Separates local QA and LLM answer counts/quality; classifies explicit abstentions and clarifications; records provider mode/model/timeout. |
| No provider setup instructions. | Added [Ollama setup guide](../LLM_SETUP.md), environment configuration and Docker Compose forwarding. |

The simulator remains enabled unless configured otherwise. Both acceptance thresholds
remain 0.5. Accepted QA answers still use the existing 100-entry cache. Generated
answers are not cached in this first provider integration; citation validity is not
proof of correctness. No course content or reference questions were changed.

Verification: 46 tests passed, including grounded request construction, citation and
schema validation, timeout/unavailable-provider handling, API bypass for local answers,
configuration checks, and separate evaluation metrics. Simulated-mode evaluation
with the real QA models was rerun to check for routing regressions.

**Limitations:** Ollama was not available on the machine's command path. No real
Ollama generation or quality benchmark was run. Users must install/start Ollama and
configure an installed model before enabling it. Timeout limits socket operations,
not the whole end-to-end request. Provider output still requires answer-quality review.

## 9. Reduce cache capacity to 10 entries

Recorded: 2026-09-24.

| Before | Improved / added |
| --- | --- |
| Default cache held up to 100 question–response entries per process. | Reduced to 10 entries at the user's request. |

LFU eviction and exact-question matching are unchanged. Only accepted extractive
QA answers are cached; simulated and generated fallback responses remain uncached.
Restart the backend to apply the new capacity. Earlier entries above retain their
historical capacity values. Verification: the existing regression suite passed.

## 10. Automatic backend .env loading

Recorded: 2026-09-24.

| Before | Improved / added |
| --- | --- |
| Settings had to be exported or sourced manually. | Application fallback configuration and evaluation startup load `code/backend/.env` automatically using python-dotenv. |
| No checked-in environment template. | Added `.env.example` for the chosen `llama3.2:1b` setup. |

The file path is independent of the working directory. Exported settings take
precedence, and evaluation CLI arguments override their supported settings. The
existing repository-root ignore rules already protect local .env files, so no
duplicate ignore rule was added. Existing local settings were not overwritten.
Install updated requirements and restart the backend. Verification: 48 tests passed,
including loading, missing-file defaults, and exported-variable precedence.

## 11. Fix small-model citation validation failures

Recorded: 2026-09-24. Branch: `feature/llm-fallback`.

| Before | Improved / added |
| --- | --- |
| Abstentions with valid citations were rejected as invalid responses. | Allow known source citations on abstentions and clarifications, retaining unknown-source rejection. |
| Citation schema allowed any strings and unbounded repetition. | Constrain citation values to the current excerpt IDs and bound the list length. |
| Prompt did not explicitly describe acronym evidence or answer-status selection. | Clarified these instructions without supplying evaluation reference answers. |

Live llama3.2:1b reproduction first returned a cited abstention. Subsequent testing
also exposed filenames as citations and repetition causing truncation. After the
fix, the live SISD response contained the correct expansion and a valid citation
and passed the backend validator. It still used clarification status incorrectly;
model-quality limitations remain. Verification: 49 tests passed. Restart Flask to
load the changes; debug mode is off, so running processes do not reload automatically.

## 12. Cache successful LLM responses alongside local QA

Recorded: 2026-09-24. Branch: `feature/llm-fallback`.

| Before | Improved / added |
| --- | --- |
| Only QA strings were cached inside the question-answering service. | Moved caching to an answer coordinator with one shared 10-entry LFU cache for QA and validated, cited LLM responses. |
| Repeated generated answers called both QA and Ollama again. | Check the response cache before either model; preserve source/provider/model metadata and citations. |
| Response provenance could be mistaken for evidence of a fresh provider call. | Added `cache_hit` to successful API responses and cache-hit counts to evaluation summaries. |
| A cited statement labelled clarification remained unresolved. | Ask the model once to correct a declarative clarification's status; cache only if it returns an accepted answer. No automatic promotion based on text heuristics. |

Placeholders, errors, abstentions, and clarification requests remain uncached.
Keys include category and exact trimmed question. Cache access is synchronized and
stored responses are copied. Concurrent misses can still make duplicate calls.
Restarting clears cache and applies provider/model/data configuration changes.
The status-correction path may make two provider calls, each with the configured
timeout. Verification: 55 tests passed, covering LLM reuse, shared total capacity,
LFU eviction, provenance, non-answer exclusion, mutation isolation, concurrent hits,
and bounded status correction. A live two-request check with llama3.2:1b returned
the SISD expansion with cache_hit false, then the same cited answer with cache_hit
true. The response no longer carried needs_clarification in that check. Existing
historical entries describe older behavior.

## 13. Unsupported-question handling

Date: 2026-09-24. Branch: `feature/unsupported-question-handling`.

| Before | Improved |
| --- | --- |
| Ambiguous or unsupported questions reached the answer models without explicit checks. | Missing subjects, unknown named identifiers, and very weak retrieval matches produce standalone limitation statements. |
| Provider responses supported an extra conversational status. | Provider schema and validator accept only `answer` or `abstain`. |
| Ambiguous evaluation cases expected conversational responses. | The standard `evaluation/cases.json` now expects abstention for all seven ambiguous/unsupported cases. |

Answers remain restricted to supplied notes. The 0.5 answer thresholds and 10-entry
answer cache remain unchanged. Limitation statements are not cached.
Removed the separate evaluation dataset, legacy status handling, conversational
metric, and superseded reports introduced during this branch. Earlier committed
reports remain historical evidence; their scores have not been rewritten.

Verification: 65 tests passed. The simulated evaluation handled all seven ambiguous/unsupported cases correctly, with zero operational errors. This does not measure live Ollama answer quality.

Current evaluation report: [unsupported-question-handling.json](../evaluation/baselines/unsupported-question-handling.json).

## 14. Backend cleanup

Date: 2026-09-24. Branch: `feature/unsupported-question-handling`.

| Before | Improved |
| --- | --- |
| A legacy passage-loading wrapper existed only for a test, alongside an unused threshold alias. | Removed both; the dataset test exercises the production course loader directly. |
| The relevance guard accepted unused passages and combined all validation in one condition. | Removed the unused argument and separated score validation from the relevance decision. |
| Evaluation duplicated provider environment parsing. | Application and evaluator share `FallbackConfig.from_environment`, with an explicit evaluation mode override. |
| Fallback exception handling repeated exception aliases/subclasses and re-raised errors unchanged. | Simplified handlers while retaining timeout, unavailable-provider, and invalid-response codes. |
| Dataset validation advertised obsolete version 1 support. | The evaluator explicitly requires the current version 2 dataset. Historical reports remain unchanged. |

Also simplified rejection-reason selection and removed a redundant temporary
variable. No changes to the 10-entry cache, 0.5 acceptance thresholds, notes-only
answer policy, or API response format.

Verification: all 65 tests passed, including environment override precedence,
provider error mapping, cache behavior, and policy routing. All 31 evaluation
cases and their source quotations validated. No live Ollama evaluation was run
for this refactor.

## 15. Strict Q&A confidence threshold

Date: 2026-09-24. Branch: `feature/unsupported-question-handling`.

The 0.5 Q&A threshold was retained during refactoring. Its boundary now follows
the requested strict rule: accept only scores greater than 0.5, rather than
accepting equality. Scores at or below 0.5 continue to fallback; source-span and
non-empty-answer checks still apply. Retrieval acceptance is unchanged.
Boundary tests and confidence-sweep tests cover equality and values above it.

## 16. Answer source attribution

Date: 2026-09-24. Branch: `feature/answer-source-attribution`.

| Before | Improved |
| --- | --- |
| Local Q&A returned answer text without evidence. | Structured local answers include `source: local_qa` and the selected file, topic, chunk index, and actual model context. |
| Ollama citations contained file and topic only. | Both answer paths use the same citation shape: `id`, `source`, `topic`, `chunk_index`, `excerpt`. |
| Non-answer responses could expose considered sources as citations. | Policy responses, simulations, and Ollama abstentions return `sources: []`. |
| Attribution had no evaluation metrics. | Reports compare unique cited files against expected source files using per-answer precision and recall. |

A shared citation builder rejects absolute/traversing paths. Source IDs are local
to the response, metadata is derived from retrieval, and duplicate Ollama citation
IDs are removed. Excerpts match the actual model context, including any truncation;
chunk indices identify the retrieved chunk, whose context can include neighbors.
The complete structured answer is cached, preserving origin and citations on hits.
The internal Q&A service now returns a response dictionary rather than plain text.
API answer text remains in `answer`; clients receive additional metadata.

Verification: 69 tests passed, including selected-source attribution, exact Ollama
excerpts, duplicate citations, path rejection, non-answer sources, cache preservation,
and metric denominators. The [31-case simulated evaluation](../evaluation/baselines/answer-source-attribution.json)
recorded zero operational errors, 10 local answers with 9 exact matches, 14 simulated
fallbacks, and 7 correct policy decisions. File precision was 0.90 and recall 0.85
across the 10 returned local answers. These measure file agreement, not semantic
support. Ollama protocol tests use mocked responses; no live Ollama quality claim.

The 10-entry cache, strict Q&A score > 0.5 requirement, and notes-only policy remain.
No course materials or question/reference answers changed. Restart Flask to load
these changes and discard old in-memory cache entries.

## 17. Cache metrics and configuration

Date: 2026-09-25. Branch: `feature/cache-metrics-and-config`.

| Before | Improved |
| --- | --- |
| Cache capacity was fixed at 10. | `CACHE_CAPACITY` configures a positive integer capacity, default 10, with startup validation. |
| Cache operations had no counters. | Track hits, misses, inserts, updates, evictions, entry count, and hit rate. |
| No public statistics snapshot. | `GET /cache/stats` returns aggregate numbers under the existing cache lock, with no-store headers and no cached content. |
| Evaluation used mostly unique questions. | A repeat-question workload compares capacities using the same 124 requests and fresh caches. |
| Reports had only individual request timings. | Add count/mean/median timing groups for cache hits and each answer origin, plus cache snapshots. |

Before-lookup rejections are excluded from miss counts. Later refusals and errors
still count as misses when a lookup occurred. The low-level LFU class requires
caller synchronization; production access uses the AnswerService lock. Restarts
reset entries and metrics; workers are independent. Concurrent misses may still
issue duplicate model requests. Notes-only answers, strict QA score > 0.5, source
attribution, LFU eviction, and default capacity 10 are unchanged.

Verification: all 73 tests passed, including environment validation, exact counter
accounting, concurrent hits, endpoint privacy, and repeated workload construction.
The [capacity comparison](../evaluation/baselines/cache-capacity-comparison.json)
ran 124 requests for each capacity with real local models and simulated fallback,
with zero operational errors. Capacities 2/5 had 20 hits and 84 misses (19.2%);
10/20 had 30 hits and 74 misses (28.8%) and zero evictions. Twenty requests per run
were rejected before lookup. Capacity 20 added no benefit over 10 on this workload.
Timings include cold initialization in the first run and are descriptive, not a
controlled speedup claim. Live Ollama/cache behavior was not benchmarked.

Set `CACHE_CAPACITY=10` in `.env`, restart Flask, then inspect `/cache/stats`.
See the evaluation README for the repeated workload command and timing caveats.

## Maintaining this history

For each future backend change, append an entry in the same change/PR:

1. Date and actual branch name, if known.
2. The problem and a before/after table.
3. API, data, configuration, or run-command changes the user must know about.
4. Verification results and links to saved evidence, where available.
5. Remaining limitations and tradeoffs.

Keep earlier entries as historical snapshots. Do not replace old measurements with
new ones or describe proposed work as implemented. Record commit or PR links only
when they exist and have been verified.
