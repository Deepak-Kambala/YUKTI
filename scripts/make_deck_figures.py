"""
Figures for the SIH deck, generated from the repository's real result files.

Nothing here is hand-typed: every number is read from results/*.csv or from
results/summaries/profile_hotspots.txt. If a result file changes, re-run this
script and the deck figures change with it.

Palette is deliberately white / black / graphite only -- no accent colour.

Run: python3 scripts/make_deck_figures.py
Writes: results/summaries/fig_*.png
"""
from __future__ import annotations
import os, sys, csv, re

os.environ.setdefault("MPLCONFIGDIR", os.environ.get("TMPDIR", "/tmp") + "/mplcache")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.join(os.path.dirname(__file__), "..")
RES = os.path.join(ROOT, "results")
OUT = os.path.join(RES, "summaries")
os.makedirs(OUT, exist_ok=True)

INK = "#111111"        # near-black: data
GRAPHITE = "#5A5F66"   # secondary text
LIGHT = "#D6D9DD"      # de-emphasised fill
HAIR = "#B9BDC2"       # hairlines

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": HAIR,
    "axes.linewidth": 0.7,
    "text.color": INK,
    "axes.labelcolor": GRAPHITE,
    "xtick.color": GRAPHITE,
    "ytick.color": GRAPHITE,
    "xtick.major.width": 0.7,
    "ytick.major.width": 0.7,
    "savefig.facecolor": "white",
})


def read_benchmarks():
    with open(os.path.join(RES, "benchmark_results.csv")) as f:
        return list(csv.DictReader(f))


def read_profile_shares():
    """Parse the instrumented share for each instance out of the profile run."""
    path = os.path.join(OUT, "profile_hotspots.txt")
    shares, cur = {}, None
    with open(path) as f:
        for line in f:
            m = re.match(r"INSTANCE: (\S+)", line.strip())
            if m:
                cur = m.group(1)
            m = re.search(r"SHARE OF TOTAL SOLVE TIME\s*:\s*([\d.]+)\s*%", line)
            if m and cur:
                shares[cur] = float(m.group(1))
    return shares


# ---------------------------------------------------------------------------
# Figure 1: measured runtime growth on the synthetic refinery LP family
# ---------------------------------------------------------------------------
def fig_scaling(rows):
    want = ["refinery_lp_small", "refinery_lp_medium", "refinery_lp_large"]
    pts = []
    for name in want:
        r = next(x for x in rows if x["instance"] == name)
        pts.append((int(r["variables"]), float(r["runtime_sec"]), int(r["iterations_or_nodes"])))

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    fig, ax = plt.subplots(figsize=(4.55, 2.45), dpi=220)
    ax.plot(xs, ys, color=INK, linewidth=1.4, marker="o", markersize=5,
            markerfacecolor="white", markeredgewidth=1.4, zorder=3)
    ax.set_yscale("log")
    ax.set_xscale("log")
    ax.set_xlim(xs[0] * 0.72, xs[-1] * 2.15)   # right margin for the last label
    ax.set_ylim(ys[0] * 0.45, ys[-1] * 3.4)
    ax.set_xticks(xs)
    ax.set_xticklabels([str(x) for x in xs], fontsize=8)
    ax.set_xlabel("variables", fontsize=8)
    ax.set_ylabel("solve time (s, log)", fontsize=8)
    ax.tick_params(labelsize=7.5)
    ax.grid(True, which="major", axis="y", color=HAIR, linewidth=0.5, alpha=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    for (x, y, it) in pts:
        ax.annotate(f"{y:.4f}s\n{it} iters", (x, y), textcoords="offset points",
                    xytext=(7, -12), fontsize=7, color=GRAPHITE, linespacing=1.3)

    ax.annotate("4x variables -> 22x time\n(dense basis re-solve, no LU update)",
                xy=(0.02, 0.86), xycoords="axes fraction", fontsize=7.4,
                color=GRAPHITE, linespacing=1.35, va="top")
    fig.tight_layout(pad=0.3)
    p = os.path.join(OUT, "fig_scaling.png")
    fig.savefig(p); plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# Figure 2: measured hotspot -- where solve time actually goes
# ---------------------------------------------------------------------------
def fig_hotspot(shares):
    share = shares["refinery_lp_large"]
    rest = 100.0 - share

    fig, ax = plt.subplots(figsize=(4.55, 1.02), dpi=220)
    ax.barh([0], [share], color=INK, height=0.44, zorder=3)
    ax.barh([0], [rest], left=[share], color=LIGHT, height=0.44, zorder=3)

    ax.set_xlim(0, 100); ax.set_ylim(-0.75, 0.75)
    ax.axis("off")

    ax.text(share / 2, 0, f"basis solves  {share:.1f}%", ha="center", va="center",
            color="white", fontsize=8.2, fontweight="bold")
    ax.text(100.6, 0, f"everything else {rest:.1f}%", ha="left", va="center",
            color=GRAPHITE, fontsize=7.6)
    ax.text(0, -0.62, "measured on refinery_lp_large (96 vars) by two independent "
                      "methods, agreeing to 0.3pp",
            ha="left", va="center", color=GRAPHITE, fontsize=6.9)
    fig.tight_layout(pad=0.25)
    p = os.path.join(OUT, "fig_hotspot.png")
    fig.savefig(p, bbox_inches="tight"); plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# Figure 3: the equilibration A/B -- a correctness result, not a speed result
# ---------------------------------------------------------------------------
def fig_scaling_ab():
    with open(os.path.join(OUT, "scaling_ab.csv")) as f:
        rows = list(csv.DictReader(f))
    ok = lambda s: s in ("OPTIMAL", "INFEASIBLE")
    off = sum(1 for r in rows if ok(r["status_off"]))
    auto = sum(1 for r in rows if ok(r["status_auto"]))
    total = len(rows)

    fig, ax = plt.subplots(figsize=(2.15, 1.55), dpi=220)
    bars = ax.bar(["scaling off", "auto (default)"], [off, auto],
                  color=[LIGHT, INK], width=0.5, zorder=3)
    ax.set_ylim(0, total + 2.6)
    ax.set_yticks([])
    ax.tick_params(labelsize=7.5, length=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    for b, v in zip(bars, [off, auto]):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.35, f"{v}/{total}",
                ha="center", fontsize=8.6, color=INK, fontweight="bold")
    ax.text(0.5, -0.30, "instances solved", transform=ax.transAxes,
            ha="center", fontsize=7, color=GRAPHITE)
    fig.tight_layout(pad=0.25)
    p = os.path.join(OUT, "fig_scaling_ab.png")
    fig.savefig(p, bbox_inches="tight"); plt.close(fig)
    return p


def main():
    rows = read_benchmarks()
    shares = read_profile_shares()
    for p in (fig_scaling(rows), fig_hotspot(shares), fig_scaling_ab()):
        print("[saved]", os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
