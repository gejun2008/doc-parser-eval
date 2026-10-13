# Vendored third-party code

| Path | Upstream | Version | License |
|---|---|---|---|
| `olmocr/bench/`, `olmocr/repeatdetect.py` | [allenai/olmocr](https://github.com/allenai/olmocr) | commit `ab294c6a` | Apache-2.0 (`olmocr/LICENSE`) |
| `olmocr/bench/katex/katex.min.*`, `auto-render.min.js` | [KaTeX](https://github.com/KaTeX/KaTeX), as shipped by olmocr | as in olmocr `ab294c6a` | MIT |

Only the modules needed for scoring are included. The single local change is
`olmocr/__init__.py`, which drops the upstream version import. Scoring logic is not modified.
To update, copy the same files from a newer olmocr commit, change the version above,
and re-run `python -m eval.tests`.
