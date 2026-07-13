#!/usr/bin/env python3
"""Generate the charts for the "privacy-plus eval" blog post from the per-case
CSV dumps in data/ (canonical in-cluster runs) and data-c1/ (NER-shim A/B runs).

Every number in the post comes from these CSVs; this script is the only image
pipeline — re-run it after regenerating the CSVs and the figures stay honest.

Usage:  python3 make_charts.py [--outdir ../../images]
"""
import argparse
import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX = "privacy-plus-eval-"          # flat images/ dir => per-post prefix
THRESHOLD = 0.50                        # policy threshold (code/privacy-plus.yaml)

RED = "#c0392b"      # leaks (the metric that matters)
BLUE = "#2980b9"     # false positives (annoying, not dangerous)
GRAY = "#7f8c8d"

# ---------------------------------------------------------------- loading


def load(*dirs):
    """rows: run_label, lang, id, category, expect, decision, correct,
    privacy_score, classifier_fired, latency_ms"""
    rows = []
    for d in dirs:
        full = os.path.join(HERE, d)
        for f in sorted(os.listdir(full)):
            if not f.endswith(".csv"):
                continue
            with open(os.path.join(full, f), newline="") as fh:
                for r in csv.DictReader(fh):
                    r["privacy_score"] = float(r["privacy_score"])
                    r["latency_ms"] = float(r["latency_ms"])
                    r["correct"] = int(r["correct"])
                    r["classifier_fired"] = int(r["classifier_fired"])
                    rows.append(r)
    return rows


def leaks(rows):
    """leak = expect local (sensitive) but routed sota."""
    return sum(1 for r in rows if r["expect"] == "local" and r["decision"] == "sota")


def fps(rows):
    """false positive = expect sota (benign) but routed local."""
    return sum(1 for r in rows if r["expect"] == "sota" and r["decision"] == "local")


def sel(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


# ---------------------------------------------------------------- charts


def annotate(ax, bars):
    for b in bars:
        ax.annotate(f"{int(b.get_height())}", (b.get_x() + b.get_width() / 2, b.get_height()),
                    ha="center", va="bottom", fontsize=9, fontweight="bold")


def chart_leaks_by_config(data, outdir):
    configs = [("rules-only", "rules only"),
               ("C2:granite", "+ C2 Granite-2B"),
               ("C2:qwen7b", "+ C2 Qwen-7B")]
    langs = [("en", "English"), ("it", "Italian")]
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4), sharey=True)
    for ax, metric, color, title in ((axes[0], leaks, RED, "Leaks (sensitive → SOTA)"),
                                     (axes[1], fps, BLUE, "False positives (benign → LOCAL)")):
        w = 0.35
        for i, (lang, lname) in enumerate(langs):
            vals = [metric(sel(data, run_label=c, lang=lang)) for c, _ in configs]
            bars = ax.bar([x + (i - 0.5) * w for x in range(len(configs))], vals, w,
                          label=lname, color=color, alpha=1.0 if i == 0 else 0.55)
            annotate(ax, bars)
        ax.set_xticks(range(len(configs)))
        ax.set_xticklabels([l for _, l in configs])
        ax.set_title(title, fontsize=11)
        ax.legend()
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("cases (out of 332 per language)")
    fig.suptitle("Privacy gate outcomes per configuration — 332 cases × 2 languages", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, PREFIX + "leaks-by-config.png"), dpi=150)
    plt.close(fig)


def chart_leaks_by_category(data, outdir):
    cats = sorted({r["category"] for r in data if r["expect"] == "local"})
    rules = {c: leaks(sel(data, run_label="rules-only", category=c)) for c in cats}
    c2 = {c: leaks(sel(data, run_label="C2:qwen7b", category=c)) for c in cats}
    cats.sort(key=lambda c: -rules[c])
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    w = 0.38
    b1 = ax.bar([x - w / 2 for x in range(len(cats))], [rules[c] for c in cats], w,
                label="rules only", color=RED)
    b2 = ax.bar([x + w / 2 for x in range(len(cats))], [c2[c] for c in cats], w,
                label="+ C2 Qwen-7B", color=GRAY)
    annotate(ax, b1)
    annotate(ax, b2)
    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels(cats, rotation=30, ha="right")
    ax.set_ylabel("leaks (EN + IT pooled)")
    ax.set_title("Where the leaks live: leaks per category, rules-only vs +C2", fontsize=12)
    ax.legend()
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, PREFIX + "leaks-by-category.png"), dpi=150)
    plt.close(fig)


def chart_c1_shootout(data, data_c1, outdir):
    # rules-only panel: Presidio baseline vs each shim backend
    rules_backends = [("rules-only", "Presidio\n(baseline)", data),
                      ("rules-c1:openmed-ctx", "OpenMed\n(ctx map)", data_c1),
                      ("rules-c1:gliner2", "GLiNER2\n(full map)", data_c1),
                      ("rules-c1:gliner2-names", "GLiNER2\n(names)", data_c1),
                      ("rules-c1:gliner2-ctx", "GLiNER2\n(ctx)", data_c1)]
    c2_backends = [("C2:qwen7b", "Presidio\n+ C2", data),
                   ("c2:qwen7b+c1:gliner2-names", "GLiNER2 names\n+ C2", data_c1),
                   ("c2:qwen7b+c1:gliner2-ctx", "GLiNER2 ctx\n+ C2", data_c1)]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4),
                             gridspec_kw={"width_ratios": [5, 3]}, sharey=True)
    for ax, backends, title in ((axes[0], rules_backends, "rules only (no C2)"),
                                (axes[1], c2_backends, "with C2 (Qwen-7B)")):
        w = 0.35
        for i, (lang, lname, alpha) in enumerate((("en", "English", 1.0), ("it", "Italian", 0.55))):
            vals = [leaks(sel(src, run_label=rl, lang=lang)) for rl, _, src in backends]
            bars = ax.bar([x + (i - 0.5) * w for x in range(len(backends))], vals, w,
                          label=lname, color=RED, alpha=alpha)
            annotate(ax, bars)
        ax.set_xticks(range(len(backends)))
        ax.set_xticklabels([l for _, l, _ in backends], fontsize=9)
        ax.set_title(title, fontsize=11)
        ax.legend()
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("leaks (out of 332 per language)")
    fig.suptitle("C1 shootout — leaks per NER backend (same corpus, same engine)", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, PREFIX + "c1-shootout.png"), dpi=150)
    plt.close(fig)


def chart_threshold_sweep(data, outdir):
    ts = [t / 100 for t in range(0, 101, 5)]
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4), sharey=True)
    for ax, lang, lname in ((axes[0], "en", "English"), (axes[1], "it", "Italian")):
        rows = sel(data, run_label="C2:qwen7b", lang=lang)
        sens = [r["privacy_score"] for r in rows if r["expect"] == "local"]
        ben = [r["privacy_score"] for r in rows if r["expect"] == "sota"]
        lk = [sum(1 for s in sens if s < t) for t in ts]      # score < t -> SOTA -> leak
        fp = [sum(1 for s in ben if s >= t) for t in ts]      # score >= t -> LOCAL -> fp
        ax.plot(ts, lk, color=RED, marker="o", ms=3, label="leaks")
        ax.plot(ts, fp, color=BLUE, marker="o", ms=3, label="false positives")
        ax.axvline(THRESHOLD, color=GRAY, ls="--", lw=1)
        ax.annotate(f"threshold {THRESHOLD}", (THRESHOLD, ax.get_ylim()[1] * 0.55),
                    rotation=90, fontsize=8, color=GRAY, ha="right")
        ax.set_title(lname, fontsize=11)
        ax.set_xlabel("decision threshold on privacy_score")
        ax.legend()
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("cases (out of 332)")
    fig.suptitle("Leaks vs false positives across the decision threshold (+C2 Qwen-7B run)",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, PREFIX + "threshold-sweep.png"), dpi=150)
    plt.close(fig)


def chart_latency(data, outdir):
    # The two C2 models are pooled into ONE series: both sit behind the same
    # external stand-in endpoint, so their latency is a property of the lab
    # network + serving, NOT of the models — splitting them per model would
    # invite a comparison the data cannot support. The portable datum is the
    # RATIO to the rules path, which motivates gray-zone-only invocation.
    c2 = [r["latency_ms"] for rl in ("C2:granite", "C2:qwen7b")
          for r in sel(data, run_label=rl) if r["classifier_fired"]]
    series = [("rules path (NER)\nin-cluster", [r["latency_ms"] for r in sel(data, run_label="rules-only")]),
              ("C2 call\nexternal stand-in endpoint", c2)]
    fig, ax = plt.subplots(figsize=(8, 4))
    bp = ax.boxplot([v for _, v in series], tick_labels=[n for n, _ in series],
                    showfliers=True, patch_artist=True, widths=0.4,
                    flierprops={"ms": 3, "alpha": 0.4})
    for patch, color in zip(bp["boxes"], [BLUE, RED]):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    for idx, (name, vals) in enumerate(series):
        med = sorted(vals)[len(vals) // 2]
        ax.annotate(f"median {med:.0f} ms", (idx + 1, med),
                    xytext=(28, 0), textcoords="offset points", fontsize=9, va="center")
    ax.set_yscale("log")
    ax.set_ylabel("wall time per case (ms, log scale)")
    ax.set_title("Why C2 only runs on the gray zone: rules path vs classifier call latency",
                 fontsize=12)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, PREFIX + "latency.png"), dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=os.path.join(HERE, "..", "..", "images"))
    args = ap.parse_args()
    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)

    data = load("data")
    data_c1 = load("data-c1")

    # console sanity table (compare against the post's numbers)
    print(f"{'run':<32}{'lang':<6}{'leaks':<7}{'fp':<5}{'correct'}")
    for rows in (data, data_c1):
        for rl in sorted({r["run_label"] for r in rows}):
            for lang in ("en", "it"):
                s = sel(rows, run_label=rl, lang=lang)
                print(f"{rl:<32}{lang:<6}{leaks(s):<7}{fps(s):<5}"
                      f"{sum(r['correct'] for r in s)}/{len(s)}")

    chart_leaks_by_config(data, outdir)
    chart_leaks_by_category(data, outdir)
    chart_c1_shootout(data, data_c1, outdir)
    chart_threshold_sweep(data, outdir)
    chart_latency(data, outdir)
    print(f"\ncharts written to {outdir}/{PREFIX}*.png")


if __name__ == "__main__":
    main()
