# privacy-plus eval — data & code for the blog post

Companion assets for **"I Watched My LLM Router Leak 174 Sensitive Prompts — Here's
What Finally Stopped It (Part 3)"**.

| path | contents |
|---|---|
| `privacy-plus-english.yaml` / `privacy-plus-italian.yaml` | the evaluation corpora: 332 labeled cases per language (`expect: local\|sota`). All PII is **synthetic**. |
| `data/` | per-case CSV results of the canonical in-cluster runs: rules-only, +C2 Granite-2B, +C2 Qwen-7B × {EN, IT}. |
| `data-c1/` | per-case CSV results of the C1 NER-backend experiments (GLiNER2 / OpenMed behind a Presidio-contract shim). |
| `code/privacy-plus.yaml` | the routing policy: detectors, weights, threshold(s), NER and classifier config. |
| `code/privacy_scoring.py` | the scoring engine: detectors A/B/C1/C2, noisy-OR aggregation, fail-closed handling. |
| `code/run_eval.py` | the eval harness that scored the corpora with the real engine and produced the CSVs. |
| `containerfiles/presidio-multilang/` | Containerfile + NLP config for the bilingual (EN+IT) Presidio analyzer image — prebuilt at `quay.io/asalvati/presidio-analyzer-multilang:0.1`. |
| `containerfiles/litellm-fasttext/` | Containerfile for the LiteLLM image with fastText language detection baked in (`lid.176.ftz`) — prebuilt at `quay.io/asalvati/litellm-privacy-plus:0.1`. |
| `make_charts.py` | generates every chart in the post from the CSVs (`python3 make_charts.py`). It also prints the leak/FP summary table, so the post's numbers can be re-derived from the raw data. |

CSV columns: `run_label, lang, id, category, expect, decision, correct, gate,
privacy_score, classifier_fired, signals, latency_ms`. A **leak** is a row with
`expect=local` and `decision=sota`.
