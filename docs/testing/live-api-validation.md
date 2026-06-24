# Live API Validation

This document explains how to run the evaluator regression entry and the opt-in live API validation entry.

## Purpose

- `tests/acceptance/test_evaluator_regression.py`
  Runs stable offline evaluator regression from fixtures.
- `tests/acceptance/test_evaluator_live_api.py`
  Runs opt-in live model validation for summary generation and search query decomposition.

## Required Environment

Set `OPENAI_API_KEY` before running live validation.

Optional:

- `VSA_CONFIG`
  Override config path if you want to point at a non-default test config.

## Commands

Offline regression only:

```powershell
$env:CONDA_NO_PLUGINS='true'
$env:PYTHONIOENCODING='utf-8'
conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_regression.py -q
```

Live API validation only:

```powershell
$env:CONDA_NO_PLUGINS='true'
$env:PYTHONIOENCODING='utf-8'
$env:OPENAI_API_KEY='sk-...'
conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_live_api.py -q
```

Combined acceptance validation:

```powershell
$env:CONDA_NO_PLUGINS='true'
$env:PYTHONIOENCODING='utf-8'
conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_regression.py tests/acceptance/test_evaluator_live_api.py -q
```

## Expected Results

- Without `OPENAI_API_KEY`, live API tests should `skip` rather than fail.
- With `OPENAI_API_KEY`, live API tests should execute real model calls.
- Offline regression should remain stable regardless of live API availability.

## What Live API Tests Validate

Summary path:

- real model-generated summary text
- evaluator score against expected summary terms

Search path:

- real `decompose_query()` participation through `search_agent`
- returned `text_answer`
- `decomposed_query`
- `decomposed_attributes`
- `decomposed_has_action`
- evaluator score for the controlled search hit

## Diagnosing Failures

The live search acceptance test emits diagnostics in assertion failures. Look for:

- `text_answer`
- `decomposed_query`
- `decomposed_attributes`
- `decomposed_has_action`
- `eval_score`

If the live test fails, compare those fields against the intended query semantics before changing thresholds or fixtures.
