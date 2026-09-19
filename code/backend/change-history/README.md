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
