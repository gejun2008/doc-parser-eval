---
name: ocr-benchmark
description: Score a document parser's outputs against this OCR benchmark dataset and summarise the per-collection reports. Use when the user asks to run, score or evaluate predictions/<model> with the OCR benchmark, compare two models' results, or check that their predictions folder is complete.
---

# OCR benchmark

You orchestrate scripts. **Every number comes from `python -m eval`; never compute, estimate, round
differently or "fix" a score yourself.** If a script fails, report the error; do not work around it by editing code or data.

## Never

- Modify anything under `data/`, `gt/`, `metadata/` or `eval/`.
- Send GT files (`data/assertions/`, `gt/`, `*.jsonl`, `metadata/`) to any model or service.
- Commit `predictions/` or `results/`.
- Install packages other than `eval/requirements.txt`, `eval/requirements-parsebench.txt` (needed when
  `predictions/<model>/parsebench/` exists) and `eval/requirements-math.txt` (only if the user asks for math) without asking.
- Install `parse-bench` from PyPI: it is a different build from the vendored, pinned one.
- Average collections into one overall score, or report a rate for a stratum marked *insufficient sample*.

## Steps

1. **Find the predictions folder.** Default `predictions/<model>/`. Ask if it is ambiguous.
   Check `predictions/<model>/run_card.yaml` exists with `model` and `input_mode` (and `dpi` if `input_mode: image`).
   If missing, ask the user for the values and create it; do not guess.
2. **Check the environment** (once per machine):
   ```
   python -m pip install -r eval/requirements.txt
   python -m pip install -r eval/requirements-parsebench.txt   # if ParseBench predictions exist
   python -m eval.tests
   ```
   If the tests fail, stop and report: the scorer is not trustworthy on this machine.
3. **Check the data:** `python -m eval verify --quick`. Problems → report them (usually `git lfs pull` is needed) and stop.
4. **Score:** `python -m eval score predictions/<model>`.
   Add `--with-math` only if the user asked for math tests; if the output says math stays unscored, say so.
5. **Summarise** from `results/<model>/*.md`, quoting numbers exactly as written:
   - per collection: coverage (how many inputs had a prediction), then the strata tables;
   - every *missing* count above zero, and what it means (failed or not-run inputs count as failures;
     on ParseBench they are scored as empty documents);
   - for ParseBench, that Visual Grounding is N/A for markdown submissions (never report it as 0);
   - the "Read with care" notes of each report;
   - dataset commit, scorer version and input mode from `results/<model>/run_card.yaml`.
6. **Comparing two models:** `python -m eval compare results/<a> results/<b>`. Lead with any WARNING lines
   (different dataset commit, input mode or scorer version mean the comparison is not valid).

## If something is off

- Many `missing`: compare `predictions/<model>` with `python -m eval inputs` (writes `inputs.csv`) and list a few
  missing paths; the naming rule is in the README.
- Coverage looks right but every test fails: open one prediction and check it is Markdown text, UTF-8, for the right page.
