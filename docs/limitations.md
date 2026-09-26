# Known Limitations (measured, not estimated)

This document exists because the project's own factuality requirement says:
"If something works only for small instances, explicitly state: 'Validated on
small/medium instances; large-scale performance not yet established.'" This is that
statement, with the actual numbers behind it.

## 1. Poorly-scaled coefficients -- FIXED, with a measured cost

**Status: fixed** by `sovereign_opt/linalg/scaling.py` (iterative geometric-mean
row/column equilibration with power-of-two factors). Previously this section
documented an open failure: with coefficients spanning `1e-4` to `1e4` in the same
constraint, the absolute pivot tolerance (`1e-7`) made Phase 1 return
`NUMERICAL_FAILURE`.

What was tried first and rejected: making the singularity tolerance in
`linalg/gauss.py` scale-aware. **Measured result: it made the failure worse**, so it
was reverted. The working fix scales the *matrix*, not the tolerance.

Measured effect, from `python scripts/ab_scaling.py` (all 15 instances, three modes,
best-of-3 wall time, same process so the comparison is not confounded by machine
state):

| Mode | Total runtime | vs off | Solved (OPTIMAL\|INFEASIBLE) | Matches known optimum |
|---|---|---|---|---|
| off (`use_scaling=False`) | 1.7602 s | 1.00x | 13/15 | 6/8 |
| **auto (shipped default)** | **1.7628 s** | **1.00x** | **15/15** | **8/8** |
| always (`scaling_threshold=1.0`) | 1.9870 s | 0.89x | 15/15 | 8/8 |

The `auto` vs `off` ratio is **machine noise, not a cost of the scaling layer**, and
the run-to-run spread shows it: 1.01x, 1.00x, 1.00x, 0.99x and 0.97x across five runs
on two machines. The structural evidence is stronger than the timing: the total is
dominated by `refinery_lp_large` (~1.64 s of ~1.76 s), and on that instance `auto` and
`off` do **identical work** -- 674 iterations, identical objective to the last bit --
so no per-iteration cost is being added there at all.

Equilibration is nevertheless **gated on a magnitude-spread threshold**
(`DEFAULT_SCALING_THRESHOLD = 1e4`), because applying it unconditionally has a real,
repeatable cost: **11% slower in this run (11-14% across runs)**, because it
perturbs the pivot sequence on well-scaled models (`refinery_lp_large` 674 -> 752
iterations; `refinery_milp_small_batches` 15 -> 29 nodes). That is a *work* increase,
not noise, which is why it is treated differently from the `auto` numbers above.
With the threshold, `auto` is bit-identical to `off` on all 13 previously
validated instances -- the script asserts this per instance and prints
`auto==off: True` for each -- and engages only on `lp_ill_conditioned_1e8` and
`lp_ill_conditioned_1e12`. The threshold is derived numerically, not fitted: the
pivot floor is `1e-7`, equilibrated entries land near `1/S`, and keeping `1/S` about
three orders above the floor gives `S_max ~ 1e4`.

Residual limitation: the threshold is a heuristic on the *pre-solve* matrix spread.
A model that is well-scaled initially but becomes ill-conditioned through the
branch-and-bound bound-tightening path will not trigger scaling. Not observed on any
instance in the suite, but not excluded either.

`tests/test_simplex.py::test_poorly_scaled_still_fails_without_scaling` keeps the old
failure reproducible on demand, so the claim above stays checkable.

## 1b. Silent wrong answer on failed verification -- FOUND AND FIXED

Found by measurement while building the A/B above, not by inspection. With scaling
off, `lp_ill_conditioned_1e12` returned **`status=OPTIMAL, objective=-1e9`** when the
hand-derived optimum is `-1e7`. The independent verifier correctly set
`verified_feasible=False`, but every layer still reported the status as `OPTIMAL` --
a caller checking only `status` would have consumed a wrong answer.

Fixed in all four places that can report a result (`lp/simplex.py:solve_lp`,
`lp/orchestrator.py:solve_lp_with_presolve`, `milp/branch_and_bound.py:_finish`, and
the pure-LP shortcut in `solve_milp`): a result that fails independent verification is
downgraded to `NUMERICAL_FAILURE` with a `REJECTED (failed independent
verification): ...` message. The contract `status == OPTIMAL => verified_feasible` is
now locked by `tests/test_verification_contract.py` across the whole instance library.

## 1c. Unsound optimality claims -- FOUND BY AUDIT AND FIXED

A read-only audit of the solver against the claims in this repository found two
places where a result was labelled **proven optimal although optimality had not
been proven**. Both were demonstrated with a reproducer before any code changed,
and both are now covered by `tests/test_optimality_claims.py`.

Neither was catchable by the independent verifier (#1b), and that is the point:
verification checks that the reported point is *feasible* and that its objective
is *self-consistent*. In both failures below the point was feasible and the
objective was consistent -- what was wrong was the optimality claim attached to it.

**(a) Presolve turned UNBOUNDED into a wrong OPTIMAL.** An "empty column"
(a variable appearing in no constraint) was fixed at the bound favoured by its
cost, and when that bound was infinite the code substituted `0.0`. Reproducer --
`min -x` with `x in [0, inf)` appearing in no row:

```
presolve ON  : status=OPTIMAL   objective=1.0   verified_feasible=True   <-- WRONG
presolve OFF : status=UNBOUNDED                                          <-- correct
```

The two paths in our own code disagreed, and the wrong one passed verification.
Fixed by *not* fixing such a column: it is left in the reduced model, where the
simplex's own unboundedness test (no positive ratio-test entry) reports
UNBOUNDED. Columns whose improving bound is finite are still reduced exactly as
before.

**(b) Branch-and-bound claimed a 0.0000% gap over an unexplored tree.** The node
loop pruned on `status != OPTIMAL`, which treats `NUMERICAL_FAILURE`,
`ITERATION_LIMIT` and `UNBOUNDED` identically to `INFEASIBLE`. Only `INFEASIBLE`
is a proven-empty subtree; the others mean the node's relaxation *did not solve*,
so the subtree was neither explored nor excluded. The search then reported
`OPTIMAL` with `mip_gap = 0.0`. With one node LP forced to fail:

```
before fix: status=OPTIMAL                      mip_gap=0.0000   <-- unsound
after fix : status=FEASIBLE_NOT_PROVEN_OPTIMAL  mip_gap=0.0568
```

Note this became *reachable* because of the fail-loud rule in #1b: making
`NUMERICAL_FAILURE` a normal, expected node outcome meant branch-and-bound could
start silently discarding subtrees. Fixed by counting such nodes
(`MILPResult.abandoned_nodes`) and refusing to report `OPTIMAL` -- or
`INFEASIBLE` -- when the count is non-zero; the bound then falls back to the root
relaxation, which is the only one still known to be valid. The CLI prints an
explicit warning when the count is non-zero.

**Measured effect on the shipped instance library: none.** No instance produces
an unbounded empty column or a failing node LP, so all 15 benchmark results
(statuses, objectives, iteration/node counts, gaps, verification flags) are
bit-identical before and after. The fix removes a latent wrong answer; it does
not change any validated result.

## 2. No LU updates -- O(m^3) per simplex iteration

Every simplex iteration rebuilds the basis matrix `B` and re-solves `Bx=b` and
`B^T y = c_B` from scratch via dense Gaussian elimination. Measured consequence on
the synthetic refinery LP benchmark (results/benchmark_results.csv, actual run):

| Instance | Variables | Constraints | Iterations | Runtime |
|---|---|---|---|---|
| refinery_lp_small | 6 | 10 | 21 | 0.0026 s |
| refinery_lp_medium | 24 | 19 | 162 | 0.0742 s |
| refinery_lp_large | 96 | 37 | 674 | 1.6652 s |

From medium to large, a 4x variable increase produces a **22x runtime increase**,
decomposing into ~4.2x more iterations (674/162) and ~5.4x more cost per iteration --
the latter being the dense re-factorization of a growing basis. **Validated on
small/medium instances (roughly <=100 variables after presolve in this prototype);
large-scale (thousands to millions of variables, as the PS ultimately targets)
performance has NOT been established and would require the LU-update /
sparse-factorization work listed in the roadmap.**

### 2a. How much of the runtime is this, exactly? (measured)

`scripts/profile_hotspots.py` measures it two independent ways, because each has a
known bias: cProfile is accurate about call structure but inflates absolute time on
many small calls, while direct `perf_counter` instrumentation of the two basis-solve
entry points has near-zero overhead but sees only the functions it wraps. Saved
output: `results/summaries/profile_hotspots.txt`.

| Instance | Instrumented share | cProfile share | Basis solves |
|---|---|---|---|
| refinery_lp_medium (24 vars) | 97.3% | 97.1% | 484 |
| refinery_lp_large (96 vars) | 98.6% | 98.4% | 2020 |

The two methods agree to within 0.3 percentage points, so the number is real:
**roughly 98% of solve time is spent inside `linalg/gauss.py`** re-solving `Bx=b`
and `B^T y=c_B` from scratch. Everything else -- presolve, pivot selection, the
ratio test, verification, model construction -- is the remaining ~2%.

This is the measurement the acceleration roadmap is built on. It says the target
is unambiguous, and it also says what the *first* step must be: at these sizes the
basis is tens of rows, far too small to amortise GPU transfer latency, so the
correct next move is sparse LU with factorization updates **on the CPU** -- which
removes most of this cost outright rather than moving it to another processor.
GPU work is only worth evaluating on basis sizes large enough to pay for the
transfer, which this prototype does not yet reach. **No GPU experiment has been
run and no GPU speedup is claimed anywhere in this repository.**

Absolute runtimes above are from one machine and one session; only same-process
comparisons (like the A/B table in section 1) should be used for speed claims.

## 3. Upper bounds as explicit rows

Because finite upper bounds become extra `<=` constraint rows rather than being
handled natively by a bounded-variable simplex, row count (and therefore basis
size and per-iteration cost) is inflated for models with many bounded variables --
which is most of them. This compounds limitation #2.

## 4. Naive branch-and-bound

`milp/branch_and_bound.py` uses most-fractional-variable branching and solves every
node's LP relaxation from scratch (no warm start). On the synthetic refinery
instance with continuous-scale integer domains (availabilities in the hundreds,
*not* the discretized "batch" version used in the demo), this hits the default
node limit before proving optimality:

```
MILPStatus.NODE_LIMIT  objective=-20583.88  nodes_explored=5001
mip_gap=0.0049 (0.49%)  runtime=13.69s
```

This was an actual run during development (see conversation record), not a
hypothetical. It found a feasible, independently-verified incumbent within 0.5% of
the best known bound, but did not prove optimality within the default 5000-node
limit. The demo's `refinery_milp_small_batches` instance instead uses a
deliberately discretized ("batch_unit=50") integer domain, which converges to
proven optimality in 15 nodes / 0.0378 s -- documented in `industrial/refinery.py` as
an intentional demo-scale choice, not a general capability claim.

## 5. Best-bound reporting on early termination is loose

When branch-and-bound is stopped by a node or time limit (not fully explored), the
reported `best_bound` is the ROOT LP relaxation bound, not the tightest bound among
still-open nodes. This is a valid lower bound (so the MIP gap computed from it is
never wrong-direction), but it is conservative -- the true gap at termination may be
smaller than reported. Tracking per-node bounds would tighten this; not implemented.

## 6. No real Netlib/MIPLIB validation

This sandboxed execution environment has no general internet access (network
egress restricted to package registries -- see the environment's own network
configuration). No Netlib or MIPLIB files were downloaded or processed. All
benchmark instances in `benchmarks/instances.py` are hand-built, with optima
verified either by hand-derivation (cross-checked against the solver) or brute
force (the 5-item knapsack, cross-checked in `tests/test_milp.py`). If the user
supplies real `.mps` files locally, `io/mps_format.py`'s reader is available but
**untested against real external files** -- treat it as unverified until checked.

## 7. Free variables unsupported

Any variable with `lb = -inf` raises `NotImplementedError` at solve time rather
than being silently mishandled -- this is a deliberate fail-loud choice, but it
means models with genuinely unbounded-below variables cannot be solved by this
prototype without the caller supplying an artificial finite lower bound.

## 8. MPS reader is a basic subset

No RANGES section, no SOS constraints, minimal handling of vendor-specific
formatting quirks. Round-trip tested against this repo's own generated instances
in `tests/test_mps_io.py` (LP and MILP with integer markers, both passing) -- but,
per point 6 above, never tested against a real external Netlib/MIPLIB file.

## 9. Audited but deliberately NOT changed

A read-only audit of the solver against this repository's own claims produced the
two defects fixed in #1c, plus the six items below. Each was examined and left
alone on purpose. They are listed here rather than silently carried, because the
project's factuality rule says an unsupported claim must be flagged -- and because
"no demonstrated victim" is a reason to defer a change, not a reason to pretend the
issue does not exist.

**(a) `lp_mixed_units_ill_conditioned` does not actually exercise the equilibration
path.** Its note says "spread 1e9", and that is true of the model as built. But
presolve's singleton-row reduction removes one row and one column first, and the
spread of what reaches the simplex is **2.0** (measured: `1e-5` to `2e-5`), so the
instance reports `scaling: not applied` and solves identically with scaling off
(the A/B run confirms `auto==off: True` for it, and `matches_known_off: True`).
Nothing in the documentation is literally false -- #1 above already names
`lp_ill_conditioned_1e8` and `lp_ill_conditioned_1e12` as the only two instances
that cross the threshold -- but grouping this instance with them invites the wrong
inference, so it is stated explicitly here. The instance is still a valid test:
it checks that presolve handles a badly-scaled model correctly.

**(b) The `Gap` column is `0.00%` for LP rows by assignment, not by measurement.**
`scripts/run_benchmarks.py` writes `mip_gap = 0.0` for every LP row. That is
definitionally right -- a simplex-proved optimum has no gap, and there is no
branch-and-bound tree to measure one over -- but it is a literal in a results
column, and a reader is entitled to know which numbers were computed and which
were asserted. MILP rows carry a genuinely computed gap.

**(c) The ratio-test tie-break uses an absolute tolerance.** Bland's rule breaks
ties by lowest variable index, and its anti-cycling guarantee is exact only when
ties are exact; here two ratios within `1e-7` of each other are treated as tied.
No cycling has been observed on any instance. Changing the tolerance would
perturb the pivot sequence of every instance (including all 674 iterations of
`refinery_lp_large`) to fix a failure that has not been demonstrated, so it was
left unchanged -- consistent with the rule that a risky change to correct code is
not an improvement.

**(d) `ObjSense.MAX` is accepted by the API but never honored.**
`Model.set_objective` stores the sense and `lp/simplex.py` copies it into
`self.obj_sense`, but nothing ever reads it: `solve_lp` always minimizes the
stored cost coefficients, and `milp/branch_and_bound.py` documents that
convention explicitly. Every `set_objective` call in the entire repository --
solver, benchmarks, industrial generator, tests -- passes `ObjSense.MIN` and
negates coefficients by hand for maximization, so **no shipped model is
affected and no reported result is wrong**. It is still a public-API path that
would silently return a minimum where a caller asked for a maximum. Fixing it
properly means deciding whether `MAX` negates internally or is rejected at the
door; both are behaviour changes to a working solver, so neither was made
mid-audit.

**(e) The ratio test does not clamp a slightly-negative basic value.** If
round-off left `xB[i]` at, say, `-1e-12`, the computed ratio would be negative and
the step would move the wrong way. Not observed on any instance; the independent
verifier would catch the resulting point as infeasible and the fail-loud rule
(#1b) would downgrade it to `NUMERICAL_FAILURE` rather than report it, so the
failure mode is loud rather than silent.

**(f) The Phase-1 infeasibility test uses an absolute threshold**
(`phase1_obj > 1e-6`). On a badly-scaled model this could in principle
misclassify a feasible model as infeasible or vice versa. It is mitigated, not
eliminated, by the equilibration layer (#1) running before Phase 1 and by the
independent verifier checking the final point against the ORIGINAL model. No
instance in the suite triggers it.

