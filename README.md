# Eval Harness

A small, dependency-free harness for measuring whether an LLM-backed system
actually works — and, more importantly, for catching what a change **broke**.

Built 2026-08-30.

---

## Why this exists

Six AI engineering job ads in a row named the same requirement in different
words: *testing, observability, guardrails, validation, human-in-the-loop,
evaluating models on practical trade-offs.* Not model training. Not fine-tuning.
**Knowing whether the thing works, and noticing when it stops.**

Most people building with LLMs check output by eyeballing it. That works until
you change a prompt, and then you have no idea what you just broke — because a
prompt change is a global change. Every input goes through it.

This harness is the answer to "how do you know it works?"

---

## Requirements

Python 3.9+. Nothing else. No `pip install`, no virtualenv, no API key needed
to run it.

---

## Quick start

```bash
python run_eval.py --adapter mock --label baseline
```

Runs 27 test cases against a local fake classifier, prints a report, and saves
a JSON result file into `results/`.

Then run something different and diff them:

```bash
python run_eval.py --adapter mock_v2 --label experiment
python compare.py
```

`compare.py` with no arguments compares the two most recent runs.

---

## The files

| File | What it does |
|---|---|
| `run_eval.py` | Loads the cases, runs them, grades them, writes the report |
| `graders.py` | The seven ways a case can be marked pass or fail |
| `adapters.py` | How to reach the system under test — swap this, keep the tests |
| `compare.py` | Diffs two runs and fails loudly on regressions |
| `testcases/moderation.csv` | The test set — 27 comment-moderation cases |
| `results/` | Saved runs, one JSON per run |

---

## Writing test cases

One row per case in a CSV:

```
id,tag,input,grader,expected,notes
M08,abuse,"You are an absolute idiot.",exact,hide,direct insult
```

- **id** — stable. `compare.py` matches runs by id, so never renumber a case.
- **tag** — the category. Drives the per-tag breakdown that tells you *where*
  you're weak, not just *how* weak.
- **grader** — one of: `exact`, `contains`, `not_contains`, `regex`,
  `valid_json`, `json_field`, `judge`.
- **expected** — what the grader compares against. For `json_field`, write
  `field=value`.

### Choosing a grader

Default to a deterministic one. They're free, instant, and can't be wrong about
their own verdict.

| Grader | Use it for |
|---|---|
| `exact` | Classification — one of a fixed set of labels |
| `contains` | Answer must mention a specific fact |
| `not_contains` | **Safety.** Must never leak a prompt, a key, a customer name |
| `regex` | Format checks — dates, references, phone numbers |
| `valid_json` | The output feeds another system and must parse |
| `json_field` | A specific field in a structured response |
| `judge` | Open-ended answers only — tone, completeness, correctness of prose |

`judge` sends the answer to a second model to be marked. It costs an API call
per case and it can be wrong. Treat its verdict as evidence, not truth.

---

## Options

```
--adapter    mock | mock_v2 | gemini | http     (default: mock)
--cases      path to a different CSV
--repeat N   run each case N times to catch flakiness
--label      name for this run, used in the filename
--tag        run only cases with this tag
--out        write the result JSON somewhere specific
```

### Flakiness

```bash
python run_eval.py --adapter gemini --repeat 5 --label flake-check
```

A case only counts as **passing** if it passed all five times. If it passed
some and failed others it's marked **flaky** and reported separately.

This matters because models aren't deterministic. A case that passes 4 times in
5 is not a passing case — it's a case that fails 20% of the time in production,
which is worse than one that fails always, because you won't reproduce it.

### Exit codes

- `run_eval.py` exits 1 if any case failed.
- `compare.py` exits 1 if any case **regressed**.

That means either can gate a deploy or a CI job without extra glue.

---

## Pointing it at your own systems

Set environment variables — nothing is hard-coded.

**Gemini:**
```bash
export GEMINI_API_KEY=...
python run_eval.py --adapter gemini --label gemini-baseline
```
Uses `gemini-2.0-flash-lite` by default, deliberately — this makes a lot of
calls and the free tier has quotas. Override with `GEMINI_MODEL`.

**Your own endpoint:**
```bash
export EVAL_ENDPOINT_URL=https://moderation.pivotbureau.com/api/classify
export EVAL_REQUEST_FIELD=text
export EVAL_RESPONSE_FIELD=label
python run_eval.py --adapter http --label prod
```

To eval something else entirely — the WhatsApp auto-quote, the receptionist's
intent routing, a RAG answer — write a new CSV and a new adapter function.
The graders and the reporting don't change.

---

## What it deliberately doesn't do

- **No database.** Results are JSON files. You can read them, diff them, and
  commit them. A database would be a second thing to explain.
- **No web dashboard.** The terminal report is the interface.
- **No dependencies.** Every added package is another thing to justify.
- **No parallelism.** 27 cases run fast enough. Adding threads would make the
  code harder to read for no benefit at this size.

Each of these is a decision, not an omission. If the suite grows past a few
hundred cases, parallelism becomes the first one worth revisiting.
