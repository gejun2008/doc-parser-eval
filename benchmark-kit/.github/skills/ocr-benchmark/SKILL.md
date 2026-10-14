---
name: ocr-benchmark
description: Evaluate a document parser / OCR model on this benchmark. Calls the model's OpenAI-compatible endpoint (configured in predictions/<model>/run_card.yaml) on every benchmark input, or uses outputs the user already produced, then scores and summarises per collection. Use when the user asks to test, run, score or evaluate an OCR model with the OCR benchmark, compare two models' results, or check a predictions folder.
---

# OCR benchmark

You orchestrate scripts in the terminal. **Every number comes from `python -m eval`; never compute, estimate,
round differently or "fix" a score yourself.** Do not open or analyse source code under `eval/`: if a command
fails, report its error output and stop.

## Never

- Modify anything under `data/`, `gt/`, `metadata/` or `eval/`.
- Send GT files (`data/assertions/`, `gt/`, `*.jsonl`, `metadata/`) to any model or service.
- Print, echo, log or write an API key anywhere. Keys live only in the environment variable named in the run card.
- Commit `predictions/` or `results/`.
- Install packages other than `eval/requirements*.txt` without asking. Never install `parse-bench` from PyPI.
- Average collections into one overall score, or report a rate for a stratum marked *insufficient sample*.

## Steps

1. **Environment** (once per machine, inside the repo's virtual environment if there is one):
   ```
   python -m pip install -r eval/requirements.txt -r eval/requirements-parsebench.txt -r eval/requirements-run.txt
   python -m eval.tests
   python -m eval verify --quick
   ```
   Tests failing → stop: the scorer is not trustworthy on this machine. Verify problems → usually `git lfs pull`.

2. **Run card.** `predictions/<model>/run_card.yaml` must exist with `model`, `input_mode`, `dpi`.
   If the user gave an endpoint URL, it also needs an `endpoint:` block (`url`, `model`, `api_key_env`,
   `concurrency`); see README section A. Ask the user for missing values; do not guess. Ask the user to set the key
   themselves in the terminal (`$env:<api_key_env> = "..."`); never ask them to paste the key into chat.

3. **If the run card has an endpoint** (the kit calls the model):
   a. Smoke test: `python -m eval run predictions/<model> --smoke`. It must end with ok > 0 and fail = 0.
      Open one produced `.md` file and confirm it is Markdown of a document page (not an error message or empty).
      On failures, show the `status` / `error` / `finish_reason` from the newest file under `predictions/<model>/_raw/`.
   b. Tell the user the estimate the smoke run printed and offer the choice. **Default is everything**:
      - all collections (1,040 inputs) — `python -m eval run predictions/<model>`
      - only the public subsets, ParseBench 500 + olmOCR 120 — add `--collections parsebench olmocr`
      - any other subset of `financial olmocr perturbed parsebench`
   c. If the estimate is over about 30 minutes, give the user the exact command to run in their own terminal
      (long jobs may outlive this chat) and continue at step 4 when they say it finished. Re-running the same
      command resumes and retries failures; repeat until it reports no failures or the user accepts them.

   **If there is no endpoint**, the user supplies outputs: check `predictions/<model>/` against
   `python -m eval inputs` (writes `inputs.csv`) and report how many expected files are missing.

4. **Score:** `python -m eval score predictions/<model>`. Add `--with-math` only if the user asked for math tests;
   if the output says math stays unscored, say so.

5. **Summarise** from `results/<model>/*.md`, quoting numbers exactly as written:
   - per collection: coverage, then the strata tables;
   - every *missing* count above zero (failed or not-run inputs count as failures; on ParseBench, empty documents);
   - ParseBench Visual Grounding is N/A for markdown (never report it as 0);
   - the "Read with care" notes of each report;
   - dataset commit, scorer version, input mode and endpoint model from `results/<model>/run_card.yaml`.

6. **Comparing two models:** `python -m eval compare results/<a> results/<b>`. Lead with any WARNING lines
   (different dataset commit, input mode or scorer version mean the comparison is not valid).
