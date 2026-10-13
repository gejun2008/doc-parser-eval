# Vendored third-party code

| Path | Upstream | Version | License |
|---|---|---|---|
| `olmocr/bench/`, `olmocr/repeatdetect.py` | [allenai/olmocr](https://github.com/allenai/olmocr) | commit `ab294c6a` | Apache-2.0 (`olmocr/LICENSE`) |
| `parsebench_src/` (`src/`, `pyproject.toml`, `README.md`, `LICENSE`) | [run-llama/ParseBench](https://github.com/run-llama/ParseBench) | commit `3295d7f` (reports version 1.0.4) | Apache-2.0 (`parsebench_src/LICENSE`) |
| `olmocr/bench/katex/katex.min.*`, `auto-render.min.js` | [KaTeX](https://github.com/KaTeX/KaTeX), as shipped by olmocr | as in olmocr `ab294c6a` | MIT |

olmocr: only the modules needed for scoring are included; the single local change is
`olmocr/__init__.py`, which drops the upstream version import. ParseBench: unmodified source
(`uv.lock` and `leaderboard.csv` omitted). Scoring logic is not modified in either.

**PyPI `parse-bench==1.0.4` is not the same code as commit `3295d7f`** (44 files differ, including
scoring rules), although both report 1.0.4. Always install the vendored copy via
`eval/requirements-parsebench.txt`.
To update, copy the same files from a newer olmocr commit, change the version above,
and re-run `python -m eval.tests`.
