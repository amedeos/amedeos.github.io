#!/usr/bin/env python3
"""Offline evaluation harness for privacy-plus routing.

Scores every case in an eval YAML with the REAL privacy_scoring engine and the
shipped policy, compares the LOCAL/SOTA decision to the case's `expect`, and prints
a scorecard (overall, false negatives = leaks, false positives, per-category).

It reuses litellm/privacy_scoring.py (no LiteLLM dependency). C1 needs a reachable
Presidio (PRESIDIO_URL) and, for language detection, the fastText model
(LID_MODEL_PATH); if the model is absent the engine treats language as uncertain and
queries all supported models (union) — which is fine for evaluation.

Env:
  POLICY_FILE     policy YAML          (default: policy/privacy-plus.yaml)
  EVAL_FILE       eval YAML            (default: eval/privacy-plus-italian.yaml)
  PRESIDIO_URL    override ner.url     (e.g. http://localhost:3000/analyze)
  LID_MODEL_PATH  override fastText model path (e.g. /tmp/lid.176.ftz)
  CSV_OUT         if set, write one row PER CASE to this path (raw per-case scores +
                  fired signals + per-case latency_ms) for downstream analysis
                  (eval/stats/analyze.py). The
                  text scorecard and the EVALROW: line are printed regardless.
  NER_PREFLIGHT_TIMEOUT  seconds to wait for Presidio to become ready before scoring
                  (default 360; only when the policy has ner.enabled). Prevents the
                  "first N cases ConnectError" contamination when a run starts while
                  Presidio is still loading its models.
  CASE_RETRIES / RETRY_SLEEP  per-case retries on a transient backend error and the
                  sleep between them (defaults 10 / 5s). On each retry, if Presidio is
                  down the harness WAITS (up to NER_RECOVER_TIMEOUT) for it to become
                  Ready again — rides out a full mid-run pod restart, not just a blip.
  NER_RECOVER_TIMEOUT  seconds to wait for Presidio to recover on a mid-run error
                  before giving up on a case (default 360).
  MAX_READY_RETRIES  optional cap on retries against a CONFIRMED-READY backend (defaults
                  to CASE_RETRIES = off). Lower it only if a new poison input reappears.
  PROGRESS_EVERY / PROGRESS_SECS  print a `[progress]` line to stderr every N cases OR at
                  least every T seconds (defaults 25 / 30) — live feedback on slow runs.

Run:  PYTHONPATH=litellm python eval/run_eval.py
"""
import asyncio
import csv
import os
import sys
import time
from collections import defaultdict

import yaml

from privacy_scoring import PrivacyScorer


def _load(path):
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def _efficiency_verdict(text, eff):
    """Offline mirror of the chain's efficiency gate (policy_hook_chain.py):
    LOCAL when the question is short AND simple AND carries no complex keyword.
    The SOTA token budget is stateful/live-only, so it is not modelled here."""
    max_chars = int(eff.get("max_prompt_chars_for_local", 280))
    simple_max_words = int(eff.get("simple_max_words", 40))
    kws = [k.lower() for k in eff.get("complex_keywords", [])]
    lowered = text.lower()
    complex_kw = any(k in lowered for k in kws)
    short = len(text) <= max_chars
    simple = len(text.split()) <= simple_max_words
    return "local" if (short and simple and not complex_kw) else "sota"


def main():
    policy_file = os.environ.get("POLICY_FILE", "policy/privacy-plus.yaml")
    eval_file = os.environ.get("EVAL_FILE", "eval/privacy-plus-italian.yaml")
    policy = _load(policy_file)

    # Chain mode: POLICY_FILE is the chain policy. Compute the FULL
    # efficiency->privacy decision offline. The privacy detectors/threshold live in
    # the referenced privacy policy (single source of truth), loaded from the same
    # directory. In privacy-plus mode `policy` IS the privacy policy (path unchanged).
    is_chain = policy.get("policy") == "chain" or "gate_order" in policy or "efficiency" in policy
    if is_chain:
        eff = policy.get("efficiency", {}) or {}
        gate_order = policy.get("gate_order", ["efficiency", "privacy"])
        privacy_name = policy.get("privacy_policy_file", "privacy-plus")
        privacy_policy = _load(os.path.join(os.path.dirname(policy_file), f"{privacy_name}.yaml"))
    else:
        eff, gate_order = {}, ["privacy"]
        privacy_policy = policy

    # Allow local overrides so the harness can reach a port-forwarded Presidio and a
    # locally-downloaded LID model without editing the shipped policy.
    ner = privacy_policy.setdefault("ner", {})
    if os.environ.get("PRESIDIO_URL"):
        ner["url"] = os.environ["PRESIDIO_URL"]
    if os.environ.get("LID_MODEL_PATH"):
        ner.setdefault("lang_detect", {})["model_path"] = os.environ["LID_MODEL_PATH"]
    # Flip C2 on for an A/B run without editing the policy file.
    if os.environ.get("CLASSIFIER_ENABLED"):
        privacy_policy.setdefault("classifier", {})["enabled"] = True
    # Lower the gray-zone floor so C2 also runs on score-0 prompts (needed to catch
    # keyword-less "implicit" sensitivity). Trade-off: more classifier calls.
    if os.environ.get("CLASSIFIER_GRAY_LOW"):
        privacy_policy.setdefault("classifier", {})["gray_low"] = float(os.environ["CLASSIFIER_GRAY_LOW"])

    threshold = float(privacy_policy.get("threshold", 0.5))
    scorer = PrivacyScorer(privacy_policy)
    eval_doc = _load(eval_file)
    cases = eval_doc.get("cases", [])
    default_lang = eval_doc.get("lang", "")
    if not cases:
        sys.exit(f"no cases in {eval_file}")

    async def decide(text):
        # Union-of-LOCAL: first gate that says LOCAL wins; SOTA only if all do.
        # Returns (decision, score, gate, signals). For an efficiency short-circuit the
        # privacy engine is never consulted, so score is a placeholder 0.0 with an empty
        # signal list and gate="efficiency" -> such rows are excluded from the privacy
        # score distribution downstream (the 0.0 is not a real privacy score).
        for gate in gate_order:
            if gate == "efficiency":
                if _efficiency_verdict(text, eff) == "local":
                    return "local", 0.0, "efficiency", []
            elif gate == "privacy":
                score, signals = await scorer.score(text)
                return ("local" if score >= threshold else "sota"), score, "privacy", signals
        return "sota", 0.0, "privacy", []

    # --- resilience to a starting / briefly-restarting NER backend --------------
    # score() FAILS CLOSED on a Presidio/classifier connection error: it stamps an
    # `error:` signal and forces score 1.0/LOCAL. For a live gate that is the safe
    # default, but for the EVAL it is contamination (a fake result), not a measurement.
    # So the harness (NOT the production engine) adds two guards:
    #   (1) PREFLIGHT — wait until the NER backend actually serves a probe before
    #       scoring, so a run started while Presidio is still loading its models does
    #       not fail-close its first N cases (the classic "first 149 ConnectError" run);
    #   (2) per-case RETRY that, on a mid-run error, WAITS for the backend to become
    #       Ready again before re-scoring — rides out a full pod restart, not just a blip.
    retries = int(os.environ.get("CASE_RETRIES", "10"))
    retry_sleep = float(os.environ.get("RETRY_SLEEP", "5"))
    preflight_timeout = float(os.environ.get("NER_PREFLIGHT_TIMEOUT", "360"))
    recover_timeout = float(os.environ.get("NER_RECOVER_TIMEOUT", "360"))
    # Optional cap on retries against a CONFIRMED-READY backend (a still-erroring case
    # then points at the INPUT tripping the backend, not an outage). Defaults to the full
    # retry budget = effectively OFF: the root-cause poison input (EMAIL/URL recognizer
    # hang) is fixed and the pod is hardened, so there's no crash-loop to guard against —
    # retry generously. Set MAX_READY_RETRIES lower only if a new poison input reappears.
    max_ready_retries = int(os.environ.get("MAX_READY_RETRIES", str(retries)))
    # Probe text: NER fires (a PERSON) and the rules already score high, so C2's gray
    # zone is skipped -> the probe exercises Presidio without spending a classifier call.
    ner_probe = "Il paziente Mario Rossi ha ricevuto una diagnosi."

    def _has_error(signals):
        return any("error" in lbl for _src, lbl, _w in signals)

    def _ner_serves():
        """True if the NER backend answers a probe without failing closed."""
        _pscore, psig = asyncio.run(scorer.score(ner_probe))
        return not _has_error(psig)

    def _wait_for_ner_ready(timeout, reason):
        """Block until the NER backend serves a probe again, or `timeout` elapses.
        Returns True if it became ready, False on timeout. Shared by the PREFLIGHT
        (a run started while Presidio is still loading) and the mid-run retry, so a
        fail-closed case actively waits for Presidio to come back up instead of
        retrying blindly against a pod that is still restarting."""
        deadline = time.time() + timeout
        waited = False
        while True:
            if _ner_serves():
                if waited:
                    print("NER backend ready — resuming.", flush=True)
                return True
            if time.time() > deadline:
                return False
            print(f"waiting for the NER backend (Presidio) to become ready ({reason})...",
                  flush=True)
            waited = True
            time.sleep(retry_sleep)

    if (privacy_policy.get("ner") or {}).get("enabled"):
        if not _wait_for_ner_ready(preflight_timeout, "preflight"):
            sys.exit("NER backend (Presidio) never became healthy within the preflight "
                     "window — is the presidio-analyzer pod Ready? Aborting to avoid a "
                     "contaminated run.")

    label = os.environ.get("EVAL_LABEL") or os.path.basename(eval_file)
    total = correct = routed_local = routed_sota = 0
    false_neg = []  # expect local, got sota  -> LEAK
    false_pos = []  # expect sota, got local  -> over-routing
    by_cat = defaultdict(lambda: [0, 0])  # category -> [correct, total]
    rows = []  # one per case, for the optional CSV_OUT dump

    # Live progress so a slow classifier run is visibly making headway (streams through
    # `oc exec`): print every PROGRESS_EVERY cases OR at least every PROGRESS_SECS seconds,
    # whichever comes first. On stderr so stdout (scorecard + EVALROW) stays clean.
    progress_every = int(os.environ.get("PROGRESS_EVERY", "25"))
    progress_secs = float(os.environ.get("PROGRESS_SECS", "30"))
    _last_progress = time.monotonic()

    for c in cases:
        expect = c["expect"]
        # A per-case backend error has two distinct causes, handled differently:
        #   * backend went down mid-run (pod restart): WAIT for it to recover, then retry
        #     — rides out a full restart without fail-closing (and contaminating) the case;
        #   * the INPUT itself trips the backend (crashes/times-out Presidio): recovering
        #     then retrying just crashes it again, so cap retries against a confirmed-ready
        #     backend at MAX_READY_RETRIES. Leftover errors stay fail-closed for the
        #     run-matrix health-guard to flag rather than crash-loop the pod ~10x.
        ready_retries = 0
        latency_ms = 0.0
        for attempt in range(retries + 1):
            _t0 = time.monotonic()
            got, score, gate, signals = asyncio.run(decide(c["text"]))
            # Wall-time of the (final) scoring call: efficiency short-circuits are ~0ms;
            # privacy-gate cases include the NER call and, when it fires, the C2 LLM call.
            # On classifier_fired rows this is the metric that varies by classifier model.
            latency_ms = (time.monotonic() - _t0) * 1000.0
            if gate != "privacy" or not _has_error(signals):
                break
            if attempt >= retries or ready_retries >= max_ready_retries:
                break
            time.sleep(retry_sleep)
            # Confirm the backend actually serves before retrying (rides out a real
            # restart); if it never recovers, stop — durably down.
            if not _wait_for_ner_ready(recover_timeout, f"case {c['id']}"):
                break
            ready_retries += 1
        ok = got == expect
        total += 1
        correct += ok
        routed_local += got == "local"
        routed_sota += got == "sota"
        cat = c.get("category", "?")
        by_cat[cat][0] += ok
        by_cat[cat][1] += 1
        if not ok and expect == "local":
            false_neg.append((c["id"], score, c["text"]))
        elif not ok and expect == "sota":
            false_pos.append((c["id"], score, c["text"]))
        rows.append({
            "run_label": label,
            "lang": c.get("lang", default_lang),
            "id": c["id"],
            "category": cat,
            "expect": expect,
            "decision": got,
            "correct": int(ok),
            "gate": gate,
            # Empty (not 0.0) when the privacy engine was never consulted, so the value
            # is never mistaken for a real privacy score in the distribution analysis.
            "privacy_score": "" if gate == "efficiency" else f"{score:.4f}",
            "classifier_fired": int(any(src == "classifier" for src, _, _ in signals)),
            "signals": PrivacyScorer.format_breakdown(signals),
            "latency_ms": f"{latency_ms:.1f}",
        })

        now = time.monotonic()
        if (progress_every > 0 and total % progress_every == 0) or \
                (now - _last_progress) >= progress_secs:
            print(f"[progress] {total}/{len(cases)} cases  last={c['id']} "
                  f"gate={gate} {latency_ms:.0f}ms", file=sys.stderr, flush=True)
            _last_progress = now

    mode = "chain (efficiency->privacy)" if is_chain else "privacy-plus"
    print(f"\n=== {mode} eval: {eval_file} ===")
    print(f"threshold={threshold}  cases={total}  correct={correct} ({correct/total:.0%})")
    print(f"routing split: LOCAL {routed_local} / SOTA {routed_sota} "
          f"({routed_sota/total:.0%} to SOTA)\n")

    print("per category (correct/total):")
    for cat in sorted(by_cat):
        ok, n = by_cat[cat]
        print(f"  {cat:14s} {ok}/{n}")

    print(f"\nFALSE NEGATIVES (expect local -> routed SOTA = LEAK): {len(false_neg)}")
    for cid, score, text in false_neg:
        print(f"  [{cid}] score={score:.2f}  {text[:70]}")

    print(f"\nfalse positives (expect sota -> routed LOCAL): {len(false_pos)}")
    for cid, score, text in false_pos:
        print(f"  [{cid}] score={score:.2f}  {text[:70]}")

    # Machine-readable one-line summary: the raw cells, pipe-joined (no padding),
    # so callers (e.g. the Ansible verify plays) can assemble an *aligned* results
    # table by padding to a shared column width. EVAL_LABEL names the config
    # (e.g. "rules-only", "C2:<model>"). Cells never contain a literal '|'.
    row = "|".join([
        label,
        str(total),
        f"{correct} ({correct/total:.0%})",
        str(len(false_neg)),
        str(len(false_pos)),
    ])
    print("\nEVALROW:" + row)

    # Optional per-case dump (raw scores + fired signals) for eval/stats/analyze.py.
    csv_out = os.environ.get("CSV_OUT")
    if csv_out:
        fieldnames = ["run_label", "lang", "id", "category", "expect", "decision",
                      "correct", "gate", "privacy_score", "classifier_fired", "signals",
                      "latency_ms"]
        os.makedirs(os.path.dirname(os.path.abspath(csv_out)), exist_ok=True)
        with open(csv_out, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {len(rows)} rows -> {csv_out}")

    # Non-zero exit if any leak, so this can gate a tuning CI step later.
    sys.exit(1 if false_neg else 0)


if __name__ == "__main__":
    main()
