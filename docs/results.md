# Results

All numbers below come from an actual execution of `scripts/run_benchmarks.py` and
`scripts/ab_scaling.py` against the code in this repository (see
`results/benchmark_results.csv`, `results/summaries/scaling_ab.csv` and
`results/raw/*.json` for the machine-readable originals; `results/summaries/*.png`
for plots generated from this same data). Nothing here is hand-typed or estimated.

Test suite: **60 passed, 0 failed, 0 xfail** (`pytest tests/ -q`, 1.79 s). The
previously disclosed xfail (poorly-scaled coefficients) is now a passing test,
because the underlying limitation was fixed -- see docs/limitations.md #1. The count
rose from 37 to 60 during a soundness audit, which added
`tests/test_optimality_claims.py` (7 tests, locking the two defects in
docs/limitations.md #1c) and `tests/test_known_optima_exact.py` (16 parametrized
tests, locking the 8 declared known optima and the solver against an exact rational
oracle). **No pre-existing test was modified, skipped or removed.**

## Benchmark table (15/15 instances, real run)

| Instance | Type | Vars | Cons | Status | Objective | Runtime (s) | Iters/Nodes | Gap | Verified |
|---|---|---|---|---|---|---|---|---|---|
| lp_textbook_2var | LP | 2 | 3 | OPTIMAL | -36.0000 | 0.0002 | 5 | 0.00% | True |
| lp_equality_diet | LP | 3 | 2 | OPTIMAL | 140.0000 | 0.0002 | 6 | 0.00% | True |
| lp_degenerate_square | LP | 2 | 1 | OPTIMAL | -4.0000 | 0.0001 | 5 | 0.00% | True |
| lp_weak_relax_base | LP | 2 | 2 | OPTIMAL | -32.0000 | 0.0003 | 9 | 0.00% | True |
| lp_ill_conditioned_1e8 | LP | 2 | 1 | OPTIMAL | -500000.0000 | 0.0002 | 6 | 0.00% | True |
| lp_ill_conditioned_1e12 | LP | 2 | 1 | OPTIMAL | -10000000.0000 | 0.0002 | 7 | 0.00% | True |
| lp_mixed_units_ill_conditioned | LP | 3 | 2 | OPTIMAL | -300500.0000 | 0.0002 | 7 | 0.00% | True |
| milp_small_ip | MILP | 2 | 2 | OPTIMAL | -20.0000 | 0.0012 | 5 | 0.00% | True |
| milp_binary_knapsack_5item | MILP | 5 | 1 | OPTIMAL | -33.0000 | 0.0012 | 1 | 0.00% | True |
| milp_weak_relaxation | MILP | 3 | 1 | OPTIMAL | -6.0000 | 0.0004 | 1 | 0.00% | True |
| milp_infeasible | MILP | 1 | 2 | INFEASIBLE | n/a | 0.0000 | 0 | n/a | n/a (correctly infeasible) |
| refinery_lp_small | LP | 6 | 10 | OPTIMAL | -20683.8910 | 0.0026 | 21 | 0.00% | True |
| refinery_lp_medium | LP | 24 | 19 | OPTIMAL | -100007.5990 | 0.0742 | 162 | 0.00% | True |
| refinery_lp_large | LP | 96 | 37 | OPTIMAL | -153338.1999 | 1.6652 | 674 | 0.00% | True |
| refinery_milp_small_batches | MILP | 6 | 10 | OPTIMAL | -18569.5000 | 0.0378 | 15 | 0.00% | True |

**Summary: 14/15 OPTIMAL, 1/15 correctly-detected INFEASIBLE, 0 numerical failures,
0 unsolved, 0 feasible-but-not-proven. 14/15 independently re-verified
feasible+objective (the 15th has no solution to verify, by design). 8/15 instances
had an independently-derived known optimum to check against -- 8/8 matched. Average
runtime 0.1189 s.**

The `Gap` column is a computed MIP gap on the four MILP rows. On LP rows it is
written as `0.00%` by `scripts/run_benchmarks.py` rather than measured -- correct
by definition for a simplex-proved optimum, but asserted rather than computed; see
docs/limitations.md #9b.

## Scaling A/B (the improvement made this session)

From `python scripts/ab_scaling.py`: all 15 instances, three modes, best-of-3 wall
time, **run back-to-back in one process** so the comparison is not confounded by
machine state across sessions.

| Mode | Total runtime | vs off | Solved (OPTIMAL\|INFEASIBLE) | Matches known optimum |
|---|---|---|---|---|
| off (`use_scaling=False`) | 1.7602 s | 1.00x | 13/15 | 6/8 |
| **auto (shipped default)** | **1.7628 s** | **1.00x** | **15/15** | **8/8** |
| always (`scaling_threshold=1.0`) | 1.9870 s | 0.89x | 15/15 | 8/8 |

Reading of this table, stated plainly:

- The improvement is **correctness, not speed**. Equilibration turns 13/15 solved
  into 15/15 and 6/8 known optima into 8/8. No speedup is claimed, because none was
  measured.
- The `auto` vs `off` ratio has landed at 1.01x, 1.00x, 1.00x, 0.99x and 0.97x across
  five runs on two machines -- i.e. it is **machine noise, not a cost of the layer**.
  The structural evidence says so more firmly than the timings: the total is
  dominated by `refinery_lp_large`, and `auto` and `off` do **identical work** there
  (674 iterations, identical objective), so nothing is being added per iteration.
- Applying equilibration unconditionally is genuinely slower -- **11% in this run,
  11-14% across runs** -- because it perturbs the pivot sequence on already-well-scaled
  models: `refinery_lp_large` goes 674 -> 752 iterations and
  `refinery_milp_small_batches` goes 15 -> 29 nodes. That is a *work* increase, not
  noise. This unfavourable measurement is why the shipped default is threshold-gated,
  and it is reported here rather than omitted.
- With the threshold, `auto` is **bit-identical to `off`** on all 13 previously
  validated instances (the script checks status, objective and iteration/node count
  per instance and prints `auto==off: True`). It engages only on
  `lp_ill_conditioned_1e8` and `lp_ill_conditioned_1e12`.

An earlier cross-session comparison during this work appeared to show a 2.64x
speedup (5.08 s -> 1.93 s total). That was **confounded by machine state**, not a
real effect of the change; the same-process A/B above supersedes it and no speedup
claim is made anywhere in this repository.

## Bug found by this measurement

With scaling off, `lp_ill_conditioned_1e12` returned **`status=OPTIMAL,
objective=-1e9`** against a hand-derived optimum of `-1e7`. The independent verifier
correctly flagged it (`verified_feasible=False`) but the status still said OPTIMAL.
All solver layers now downgrade such a result to `NUMERICAL_FAILURE`; see
docs/limitations.md #1b and `tests/test_verification_contract.py`.

## Soundness audit (read-only pass over the solver's own claims)

A read-only audit checked whether the implementation genuinely supports what this
repository claims. It found **two places where a result was labelled proven-optimal
although optimality had not been proven**, both demonstrated with a reproducer
before any code was changed:

```
(a) presolve ON  : status=OPTIMAL   objective=1.0   verified_feasible=True   <-- WRONG
    presolve OFF : status=UNBOUNDED                                          <-- correct

(b) before fix   : status=OPTIMAL                      mip_gap=0.0000        <-- unsound
    after fix    : status=FEASIBLE_NOT_PROVEN_OPTIMAL  mip_gap=0.0568
```

Neither was catchable by the independent verifier, because in both cases the
reported point *was* feasible and its objective *was* self-consistent -- only the
optimality claim was wrong. Both are fixed and locked by
`tests/test_optimality_claims.py`; full write-up in docs/limitations.md #1c.

**Measured effect on the 15 benchmark instances: none.** Status, objective,
iteration/node count, gap and verification flag are unchanged on every instance --
the fix removes a latent wrong answer without altering a single validated result.

Six further findings were examined and deliberately left unchanged (the mixed-units
instance not actually exercising the scaling path, the LP `Gap` column being an
assignment rather than a measurement, the absolute ratio-test tie-break tolerance,
`ObjSense.MAX` being accepted but never honored, an unclamped negative basic value,
and the absolute Phase-1 infeasibility threshold). They are listed with reasoning in
docs/limitations.md #9 rather than silently carried.

## Known-optimum cross-checks

The 8 declared `known_optimal` constants are **independently re-derived by exact
rational arithmetic**, by `scripts/verify_known_optima.py` -- vertex enumeration via
Cramer's rule over `fractions.Fraction` for LPs, exhaustive integer enumeration for
MILPs. It shares no code with the simplex and uses no floating point, so it is a
genuine oracle rather than the solver checking itself. Saved output:
`results/summaries/known_optima_exact.txt`.

```
8/8 declared known optima confirmed (equal as IEEE doubles to the exact optimum).
5/8 are additionally exact in rational arithmetic; the rest differ only because
the model's float coefficients are not the decimals they are written as.
```

The three `ULP` rows are worth stating precisely rather than rounding away: for the
ill-conditioned instances the exact optimum of the *float* model is not the round
decimal in `known_optimal`, because `1e-4` is not exactly `1/10000` in binary. For
example `lp_ill_conditioned_1e8`'s true optimum is
`-3689348814741910323200/7378697629483821`, which differs from `-500000` by a
relative `4.79e-17` -- below half an ulp, so it rounds to exactly the declared
double. The declared constants are therefore correct to double precision, which is
the only precision the solver works in. `tests/test_known_optima_exact.py` locks
both this and the solver's own objective against the same oracle.

The original provenance of each constant, kept for the record:

- `lp_textbook_2var`: hand-derived optimum -36, solver returned -36.0000. Match.
- `lp_equality_diet`: hand-derived optimum 140 (x=40, y=0, z=60), solver returned
  140.0000, values matched. (Note: an earlier hand-derivation attempt during
  development produced the wrong value, 100; the solver's own independent
  verification step caught the discrepancy before it reached this document. The
  exact oracle above has since confirmed 140 independently.)
- `lp_degenerate_square`: hand-derived optimum -4, solver returned -4.0000. Match.
- `lp_ill_conditioned_1e8`: x in [0, 1e6], y in [0, 1e-3], `1e-4x + 1e4y <= 50`,
  minimize `-x - 1e-3y`. The x column alone consumes the row at x = 5e5, so the
  optimum is -500000. Solver returned -500000.0000 (x=5e5, y=0). Match.
- `lp_ill_conditioned_1e12`: x in [0, 1e9], y in [0, 1e-2], `1e-6x + 1e6y <= 10`,
  minimize `-x - 1e-6y`. Optimum -1e7. Solver returned -10000000.0000. Match.
- `lp_mixed_units_ill_conditioned`: hand-derived optimum -300500 (spread 1e9 as
  built). Solver returned -300500.0000. Match. Caveat worth stating: presolve's
  singleton-row reduction collapses the spread reaching the simplex to **2.0**
  (measured), so despite its name this instance does **not** exercise the
  equilibration path -- see docs/limitations.md #9a.
- `milp_binary_knapsack_5item`: brute-forced over all 32 subsets in
  `tests/test_milp.py::test_binary_knapsack`, true optimum value 33 (items
  a+b+c+d), model minimizes negated value so objective -33. Solver returned
  -33.0000. Match. (An earlier manual guess of 27 for this instance was wrong;
  brute force corrected it before this document was written.)
- `milp_weak_relaxation`: trivial "pick the best of 3 mutually exclusive binary
  items" case, hand-derived optimum -6. Solver returned -6.0000. Match.

## Industrial case study (synthetic refinery blending)

`industrial/refinery.py` generates a synthetic (NOT real proprietary) crude-blending
LP/MILP at 3 sizes. Real, measured runtimes above show the expected super-linear
cost growth from the prototype's dense, non-LU-updated simplex (see
docs/limitations.md #2): medium (24 vars) took 0.0742 s, large (96 vars) took
1.6652 s -- a 4x variable increase for a 22x runtime increase.

A discretized-integer ("batch") variant of the small refinery instance was solved
to proven MILP optimality in 15 branch-and-bound nodes / 0.0378 s. A separate,
non-discretized integer version of the same small instance (continuous-scale
integer domains) was run during development and did **not** reach proven optimality
within the default 5000-node limit -- it stopped at a 0.49%-gap incumbent after
13.69 s. Both outcomes are reported; see docs/limitations.md #4 for the
non-discretized run's full numbers. This is included deliberately, per the
project's instruction not to hide unfavorable results.

## Run-to-run stability

Re-running the suite reproduces the **structural** results exactly -- same statuses,
same objectives, same iteration and node counts (21 / 162 / 674 / 15 on the four
refinery instances) -- because the algorithm is deterministic. Only wall-clock times
vary. Observed spread across runs in this and the preceding session, on two
machines: average benchmark runtime 0.1148-0.1235 s; A/B `off` total 1.73-1.91 s;
`refinery_lp_large` 1.62-1.73 s.

The A/B *ratios* moved too, and are reported as a range rather than a single
favourable figure: `auto` vs `off` landed at 1.01x, 1.00x, 1.00x, 0.99x and 0.97x,
and `always` at 0.89x, 0.89x, 0.88x, 0.89x and 0.86x. The conclusion drawn from this
is deliberately weak on the `auto` side -- **no runtime cost has been demonstrated,
and none is claimed either way**, since `auto` and `off` execute identical work on
the instance that dominates the total. The `always` penalty, by contrast, is a
genuine work increase (752 vs 674 iterations, 29 vs 15 nodes) and reproduces in
every run.

## Where the time goes (hotspot profile)

`python3 scripts/profile_hotspots.py` measures the runtime distribution two
independent ways -- cProfile function-level accounting, and direct `perf_counter`
instrumentation of the basis-solve entry points with the profiler off. Saved
output: `results/summaries/profile_hotspots.txt`.

| Instance | Instrumented | cProfile | Basis solves | Uninstrumented wall |
|---|---|---|---|---|
| refinery_lp_medium (24 vars) | 97.3% | 97.1% | 484 | 0.0750 s |
| refinery_lp_large (96 vars) | 98.6% | 98.4% | 2020 | 1.6646 s |

The two methods agree to within 0.3 percentage points: **~98% of solve time is
inside `linalg/gauss.py`**, re-solving `Bx=b` and `B^T y=c_B` from scratch every
iteration. Presolve, pivot selection, the ratio test, verification and model
construction together account for the remaining ~2%.

This is reported here because the roadmap's acceleration stages are justified by
it. It also constrains them: at these sizes the basis is tens of rows, which is
far too small to amortise GPU transfer latency, so the first step is sparse LU
with factorization updates **on the CPU**. No GPU experiment has been run and no
GPU speedup is claimed. See docs/limitations.md #2a.

## Plots

`results/summaries/runtime.png` and `results/summaries/bnb_nodes.png`, generated by
`scripts/plot_results.py` directly from `benchmark_results.csv` -- both are real
output, screenshot-ready for the SIH presentation.

## What was NOT run

No Netlib or MIPLIB instances (no internet access in this sandboxed build
environment -- see docs/limitations.md #6). No comparison against HiGHS, CBC,
GLPK, or any commercial solver was performed in this session, so no speed/quality
comparison claim is made anywhere in this repository. `scripts/` does not currently
include a reference-solver comparison script; that is listed in the roadmap
(docs/status.md) as future work, to be added and run only when a reference solver
is actually available in the target environment.

Absolute runtimes in the first table are from one machine and one session. Only the
same-process A/B table should be used for speed comparisons; the
`results/benchmark_results_prescaling_baseline.csv` file is kept as a record of the
pre-change run but its timings are **not** comparable with the current ones.
