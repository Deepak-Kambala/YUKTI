"""
Where does the solver's time actually go?

This script exists for one reason: the roadmap says acceleration work (sparse
factorization, then GPU kernels) should target "the measured bottleneck". That
sentence is only honest if the bottleneck has in fact been measured. This
measures it.

Two independent measurements are taken, because each has a known bias:

  1. cProfile function-level breakdown. Accurate about *which* functions are
     called and how often; inflates absolute wall time (per-call profiler
     overhead, worst on many small calls -- which is exactly our case).

  2. Direct instrumentation: wrap the two basis-solve entry points
     (gauss_solve, gauss_solve_transpose) in a perf_counter timer and run
     again with the profiler off. Much lower overhead, but only sees the two
     functions it wraps.

If the two disagree wildly, the number is not trustworthy and that is worth
knowing. If they agree, the share is real.

No claim about GPU speedup is made or implied here. This measures where CPU
time is spent today; whether a given kernel is worth moving to a GPU is a
separate experiment that has NOT been run (see docs/limitations.md).

Run: python3 scripts/profile_hotspots.py
Writes: results/summaries/profile_hotspots.txt
"""
from __future__ import annotations
import sys, os, io, cProfile, pstats, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sovereign_opt.lp.simplex as simplex_mod
from sovereign_opt.industrial.refinery import generate_refinery_instance
from sovereign_opt.lp.orchestrator import solve_lp_with_presolve

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "summaries")
os.makedirs(RESULTS_DIR, exist_ok=True)
OUT_PATH = os.path.join(RESULTS_DIR, "profile_hotspots.txt")

# The two functions that implement the basis solves. Everything the
# acceleration roadmap is about lives behind these names.
BASIS_SOLVE_NAMES = ("gauss_solve", "gauss_solve_transpose")

# Same parameters the benchmark suite uses (sovereign_opt/benchmarks/instances.py),
# so these runs are the same instances as the published benchmark rows.
SIZES = {"medium": dict(n_crudes=6, n_products=4),
         "large": dict(n_crudes=12, n_products=8)}


def _solve(size: str):
    """One full solve of a synthetic refinery LP, presolve included."""
    model = generate_refinery_instance(**SIZES[size], seed=42)
    return solve_lp_with_presolve(model)


# --------------------------------------------------------------------------
# Measurement 1: cProfile
# --------------------------------------------------------------------------
def profile_run(size: str):
    prof = cProfile.Profile()
    prof.enable()
    res = _solve(size)
    prof.disable()

    st = pstats.Stats(prof)
    total = st.total_tt

    # NOTE on double counting: gauss_solve_transpose is a thin wrapper that
    # delegates to gauss_solve (gauss.py:84). Summing the two cumtimes would
    # therefore count the shared work twice and can exceed 100%. The two
    # figures reported below are both free of that artifact:
    #   - gauss.py self time (tottime), summed: self time never double counts.
    #   - gauss_solve cumtime alone: already contains the transpose path.
    basis_tot = 0.0
    basis_entry_cum = 0.0
    basis_calls = 0
    gauss_module_tot = 0.0
    for (fname, _lineno, func), (_cc, nc, tt, ct, _callers) in st.stats.items():
        if os.path.basename(fname) != "gauss.py":
            continue
        gauss_module_tot += tt
        if func in BASIS_SOLVE_NAMES:
            basis_tot += tt
            basis_calls += nc
        if func == "gauss_solve":
            basis_entry_cum = ct

    rows = sorted(
        ((tt, ct, nc, f"{os.path.basename(fn)}:{ln}({fu})")
         for (fn, ln, fu), (_cc, nc, tt, ct, _ca) in st.stats.items()),
        reverse=True,
    )[:12]

    return {
        "status": res.status.value,
        "objective": res.objective,
        "iterations": getattr(res, "iterations", None),
        "profiled_total_s": total,
        "basis_tottime_s": basis_tot,
        "basis_entry_cumtime_s": basis_entry_cum,
        "basis_calls": basis_calls,
        "gauss_module_tottime_s": gauss_module_tot,
        "top_rows": rows,
    }


# --------------------------------------------------------------------------
# Measurement 2: direct instrumentation, profiler off
# --------------------------------------------------------------------------
def instrumented_run(size: str):
    real_solve = simplex_mod.gauss_solve
    real_solve_t = simplex_mod.gauss_solve_transpose
    acc = {"t": 0.0, "n": 0}

    def wrap(fn):
        def inner(*a, **kw):
            t0 = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                acc["t"] += time.perf_counter() - t0
                acc["n"] += 1
        return inner

    simplex_mod.gauss_solve = wrap(real_solve)
    simplex_mod.gauss_solve_transpose = wrap(real_solve_t)
    try:
        t0 = time.perf_counter()
        res = _solve(size)
        wall = time.perf_counter() - t0
    finally:
        simplex_mod.gauss_solve = real_solve
        simplex_mod.gauss_solve_transpose = real_solve_t

    return {
        "status": res.status.value,
        "objective": res.objective,
        "wall_s": wall,
        "basis_s": acc["t"],
        "basis_calls": acc["n"],
        "share": acc["t"] / wall if wall > 0 else float("nan"),
    }


def baseline_wall(size: str) -> float:
    """Uninstrumented, unprofiled wall time -- the honest absolute number."""
    t0 = time.perf_counter()
    _solve(size)
    return time.perf_counter() - t0


def main():
    out = io.StringIO()
    w = out.write

    w("Solver hotspot profile -- where CPU time actually goes\n")
    w("=" * 72 + "\n")
    w("Generated by scripts/profile_hotspots.py. Real execution, this machine,\n")
    w("this session. Absolute times are machine-specific; the SHARE is the\n")
    w("number this measurement exists to establish.\n\n")

    for size in ("medium", "large"):
        name = f"refinery_lp_{size}"
        w("-" * 72 + "\n")
        w(f"INSTANCE: {name}\n")
        w("-" * 72 + "\n")

        base = baseline_wall(size)
        w(f"Uninstrumented wall time            : {base:.4f} s\n")

        ins = instrumented_run(size)
        w(f"Instrumented wall time              : {ins['wall_s']:.4f} s\n")
        w(f"  status / objective                : {ins['status']} / {ins['objective']:.4f}\n")
        w(f"  basis solves (gauss_solve[_transpose])\n")
        w(f"    calls                           : {ins['basis_calls']}\n")
        w(f"    time in basis solves            : {ins['basis_s']:.4f} s\n")
        w(f"    SHARE OF TOTAL SOLVE TIME       : {100.0 * ins['share']:.1f} %\n\n")

        pr = profile_run(size)
        w(f"cProfile total (inflated by profiler): {pr['profiled_total_s']:.4f} s\n")
        w(f"  gauss_solve cumtime (entry point) : {pr['basis_entry_cumtime_s']:.4f} s "
          f"({100.0 * pr['basis_entry_cumtime_s'] / pr['profiled_total_s']:.1f} %)\n")
        w(f"  basis-solve self time (tottime)   : {pr['basis_tottime_s']:.4f} s "
          f"({100.0 * pr['basis_tottime_s'] / pr['profiled_total_s']:.1f} %)\n")
        w(f"  all of linalg/gauss.py (tottime)  : {pr['gauss_module_tottime_s']:.4f} s "
          f"({100.0 * pr['gauss_module_tottime_s'] / pr['profiled_total_s']:.1f} %)\n")
        w(f"  basis-solve calls                 : {pr['basis_calls']}\n")
        w("  (gauss_solve_transpose delegates to gauss_solve, so its time is\n")
        w("   already inside the cumtime above; the two are not added.)\n\n")
        w("  Top 12 functions by self time (cProfile):\n")
        w(f"    {'tottime':>9} {'cumtime':>9} {'ncalls':>9}  function\n")
        for tt, ct, nc, label in pr["top_rows"]:
            w(f"    {tt:9.4f} {ct:9.4f} {nc:9d}  {label}\n")
        w("\n")

    w("=" * 72 + "\n")
    w("READING THIS RESULT\n")
    w("=" * 72 + "\n")
    w("The two measurements bound the answer from opposite sides. Direct\n")
    w("instrumentation under-counts (it times only the two wrapped entry\n")
    w("points, not the simplex's own vector arithmetic around them); cProfile\n")
    w("over-counts small frequently-called functions relative to large ones.\n")
    w("Where they agree, the share is real.\n\n")
    w("What this does NOT show: that a GPU would be faster. Moving a kernel to\n")
    w("a GPU is worth doing only if the kernel is both dominant AND large\n")
    w("enough to amortise transfer latency. At this instance size the basis\n")
    w("matrices are tiny (tens of rows), so the correct next step is sparse\n")
    w("LU with factorization updates on the CPU -- which removes most of this\n")
    w("cost outright -- before any GPU work. No GPU experiment has been run.\n")

    text = out.getvalue()
    print(text)
    with open(OUT_PATH, "w") as f:
        f.write(text)
    print(f"[saved] {os.path.relpath(OUT_PATH)}")


if __name__ == "__main__":
    main()
