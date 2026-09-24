# Computer Architecture answer-quality evaluation

This is a small, source-grounded development benchmark for the multiprocessor
materials in `text_files`, not an evaluation of the entire Computer Architecture
syllabus. It measures the current backend without changing retrieval, thresholds,
models, cache behavior, or the API.

## Contents

`cases.json` contains 31 manually authored cases:

Every answerable case includes accepted reference answers and exact supporting
quotes with paths relative to `text_files`. All 11 course text files are covered.
Quotes establish provenance; they do not automatically prove a model response
correct. Reference answers follow the supplied notes, including their approximate
hardware limits. A course instructor should review these references before using
scores for formal assessment.

## Run

From `code/backend`, with the environment activated:

```bash
# Validate dataset structure, source paths, and quotes; no models required.
python -m evaluation.run --validate-only

# Run all questions and save the detailed report.
python -m evaluation.run

# Keep a named report for comparison across branches.
python -m evaluation.run --output evaluation/reports/my-run.json
```

The runner uses Flask's in-process test client to exercise `POST /api`, including
validation and error handling. No running HTTP server or API key is required.
The real models load on the first question and may download if not cached.
For a machine with cached models, prohibit network access with:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m evaluation.run
```

Run scoring/provenance tests along with backend regression tests:

```bash
python -m unittest discover -s tests -v
```

## Interpret the report

- **Answer exact match:** normalized match against the best accepted reference.
  Normalization ignores case, punctuation and English articles.
- **Answer token F1:** token overlap against the best reference, using token
  frequencies. This is a lexical diagnostic, not a correctness probability.
- Both answer scores average over **all 24 answerable cases**. Refusals and
  operational errors receive zero; neither is silently removed from the denominator.
- **Answer return rate:** how often answerable cases receive an answer. It does
  not say whether the answer is correct.
- **Non-answer behavior accuracy:** how often ambiguous/unsupported cases receive
  the expected behavior, separately from answer text scores.
- **Unsupported answer count:** unsupported questions that nevertheless receive
  answers. Review these for unsupported claims.
- **Operational errors:** unavailable models, HTTP errors other than the expected
  422 abstention, or invalid response shapes. A 503 is never successful abstention.

New multi-chunk runs also include context-local `retrieval` diagnostics with
candidate source/topic, similarities, QA scores, selected answer, and failure
reason. Older baseline reports do not have this field.

The report includes overall metrics, metrics by case kind, each request and
response, reference answers, supporting quotes, timing, dependency versions and
dataset/source hashes. The first request includes model initialization; timings
are not a concurrency or throughput benchmark. Each run creates a fresh app and
in-memory cache, then runs questions sequentially.

Comparison responses and semantically equivalent paraphrases require human
review. For example, token overlap may give credit to a response that reverses
hit/miss relationships. Review correctness, completeness, and whether the answer
is supported by the quoted material; do not use F1 as an automatic acceptance rule.

A completed run exits 0 even if quality is poor: this branch establishes a
baseline rather than claiming the current model passes a quality target. Operational
failures exit 2; invalid datasets raise validation errors and exit nonzero.

## Baseline and future changes

`baselines/initial.json` records the first real-model run. Ordinary local reports
under `reports/` are ignored by Git. Keep the baseline unchanged when improving
the backend, run the same cases again, and compare scores by kind and individual
responses. Hardware, model revisions, and package versions may affect results;
compare in the same environment where possible.

This small set is for development and will be visible during tuning. Before
claiming general improvement, add a separate held-out set that was not used to
choose thresholds or prompts.

The multi-chunk implementation's comparison run is saved separately as
`baselines/multi-chunk.json`. It uses identical case and course-source hashes to
`baselines/initial.json`; the original baseline remains unchanged.

## Confidence checks and cutoff comparison

`baselines/answer-confidence.json` records the real-model run with separate
retrieval (0.5) and QA (0.15) acceptance cutoffs. `baselines/confidence-sweep.json`
records QA cutoff replay on its saved candidate scores. Cases and course sources
are unchanged from the preceding baselines.

```bash
python -m evaluation.run --min-qa-score 0.15 --output evaluation/reports/confidence.json
python -m evaluation.confidence_sweep evaluation/reports/confidence.json
```

The sweep fixes retrieval, candidate selection, source-span checks, and model
outputs; it changes only the QA cutoff and reselects the best accepted candidate.
It requires complete uncached diagnostics without operational errors. This makes
it inexpensive, but it cannot predict results for new retrieval thresholds or
recover candidates that were never sent to QA. Use a fresh full evaluation for
those changes. No cases or reference answers are rewritten by the sweep.

The confidence policy and candidate rejection reasons are saved in new reports.
A high QA score for an empty answer is the model's no-answer output, not support
for a non-empty answer. Source-span membership only verifies extraction from the
context; it cannot establish that the answer is relevant or complete.

| QA minimum | Answer exact match | Answer return rate |
| --- | ---: | ---: |
| 0.00 | 58.3% | 62.5% |
| 0.15 (default) | 58.3% | 62.5% |
| 0.20 | 54.2% | 58.3% |
| 0.50 | 37.5% | 41.7% |
| 0.60 | 33.3% | 33.3% |

All four unsupported questions remained declined in this sweep, so this set
cannot establish that a higher cutoff improves unsupported-answer detection.
The incomplete comparison answer scores about 0.56; a correct answer scores about
0.19. Scores alone cannot separate them. The provisional 0.15 default preserves
known correct answers; obtain held-out positive and difficult negative examples
before claiming calibration or broader reliability.

Failure diagnosis from the multi-chunk baseline:

| Cases | Failure stage |
| --- | --- |
| ca-01, ca-05, ca-11, ca-18 | No retrieved candidate met the 0.5 cutoff |
| ca-08, ca-10, ca-14, ca-22, ca-23 | Eligible context reached QA, but all QA outputs were empty |

This stage classification does not prove the correct evidence was present in every
QA input. For example, ca-10's scalability candidate scored below the retrieval
cutoff while other contexts were evaluated. Inspect candidate sources as well as
failure reasons when planning further retrieval or model changes.

## Current prototype routing: QA cutoff 0.5 and simulated fallback

The current run is saved as `baselines/simulated-fallback.json`. The sweep respects
`fallback_mode` metadata for new reports, while retaining historical abstention
behavior for older reports. Simulated placeholders are not cached.

## Local-answer metrics and reason codes

New reports include `local_answer_count`, `local_answer_exact_match_rate`, and
`simulated_fallback_rate`. Local exact-match rate uses every local answer as its
denominator, including unsupported/ambiguous cases as non-matches; it excludes
simulated placeholders. Overall answer exact match still uses all answerable cases.
Undefined rates are null. The new measures also appear in by-kind summaries and
cutoff replay summaries. They measure text matching, not semantic correctness.

Per-case simulated responses now contain `fallback_reason`. See the backend README
for the reason-code contract. Full individual candidate rejection reasons remain
in retrieval diagnostics. `baselines/routing-diagnostics.json` records the new
real-model report format without replacing older historical reports.

## Ollama fallback evaluation

Generated explanations may differ from the short reference spans; inspect
correctness, completeness, and citations manually. The QA-only cutoff sweep rejects
Ollama-mode reports because different thresholds change which real LLM calls occur.
No live Ollama accuracy baseline has been established on this machine.

## Unsupported-question policy baseline

`baselines/unsupported-question-handling.json` records the deterministic policy
with simulated fallback for remaining questions. Questions and reference answers
are unchanged. Reports count policy responses by reason and retain model-stage
diagnostics when available. QA-cutoff replay preserves recorded policy responses
because they are independent of the QA cutoff; it does not tune the relevance floor.

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

## Attribution metrics

Reports include `source_precision`, `source_recall`, and `attribution_case_count`.
For each returned answer to an answerable case, precision measures the proportion
of unique cited files present in the expected source set; recall measures the
proportion of expected files cited. The summary averages these per-case scores.
Missing citations score zero. Non-answers and unsupported cases are excluded;
read these scores alongside answer return rate and unsupported-answer count.
These metrics measure file matching, not claim support or excerpt correctness.
The existing dataset provides expected source files; no new course material was added.
QA threshold replay omits attribution scores because it can select different passages.

`baselines/answer-source-attribution.json` records the simulated-fallback run.
