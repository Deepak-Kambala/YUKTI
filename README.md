# Sovereign Optimization Engine -- Prototype

**SIH 2026 PS 26119** -- Indigenous GPU-Accelerated Optimization Solver
(Sovereign Alternative to CPLEX/Xpress)

## What this is (and is not)

This is a **prototype** demonstrating that a from-scratch LP/MILP solving core is
feasible to build, test, and independently verify -- not a production replacement
for CPLEX/Gurobi/HiGHS. It implements genuine two-phase revised simplex and
branch-and-bound MILP, with no external optimization solver used anywhere
internally (see "Dependencies" below for exactly what libraries are used and why
they don't count as solving the optimization problem).

Every number in this README, in `docs/results.md`, and printed by `run_demo.sh`
comes from an actual execution of the code in this repository. Where something
doesn't work, it's documented in `docs/limitations.md` rather than hidden --
including a measured 11-14% slowdown from one design option that was consequently
not shipped as the default, one documented case where the branch-and-bound didn't
reach proven optimality within its node limit, and two unsound optimality claims
that a read-only audit found in this solver's own code and that are now fixed
(`docs/limitations.md` #1c).

## Motivation

Refinery scheduling, crude blending, production planning and similar Indian
industrial optimization workloads currently depend on foreign commercial solvers
(CPLEX, Gurobi, Xpress). This prototype explores what a sovereign, from-scratch
alternative's algorithmic core looks like, and honestly measures how far a
time-boxed prototype gets versus what a production engine would need.

## Why Python, not C++17 (a stated tradeoff, not a shortcut)

The PS's preferred stack is C++17 + CMake + GoogleTest. This prototype is written
in Python because the priority for THIS stage was: write an algorithm, run it,
verify it's actually correct, fix it, repeat -- for every one of simplex,
presolve, and branch-and-bound. That loop is faster in Python, and this
environment's time/token budget did not allow both a from-scratch C++ numerical
core AND the level of testing/verification the PS explicitly demands. See
`docs/architecture.md` for the full reasoning and `docs/status.md` for the
roadmap to a C++ port once the algorithm designs are validated (which is what
this prototype accomplishes).

**Crucially: numpy is used only for array storage and elementwise arithmetic.**
The actual linear-algebra solve inside simplex -- solving `Bx=b` and `B^T y=c_B`
for the basis matrix `B` every iteration -- is hand-written Gaussian elimination
with partial pivoting (`sovereign_opt/linalg/gauss.py`), not `numpy.linalg.solve`
or any other library solver. This preserves the "solver built from scratch from
mathematical foundations" requirement.

## Dependencies and why each is permitted

| Library | Used for | NOT used for |
|---|---|---|
| `numpy` | Array containers, elementwise arithmetic | Solving linear systems (see above) |
| `matplotlib` | Plotting real benchmark results | N/A |
| `pytest` | Test runner | N/A |

`scipy` is deliberately **not** a dependency: nothing in the codebase imports it,
so it was removed from `requirements.txt` rather than left installed where
`scipy.optimize` would be one import away.

No LP/MILP/QP solver library (Gurobi, CPLEX, Xpress, HiGHS, CBC, GLPK, SCIP,
OR-Tools, PuLP, Pyomo, CVXPY, scipy.optimize) is imported or called anywhere in
`sovereign_opt/`.

## Architecture

See `docs/architecture.md` for the full module map and data-flow diagrams.

```
sovereign-opt/
  sovereign_opt/{core,sparse,linalg,presolve,lp,milp,io,industrial,benchmarks}/
  tests/            pytest suite (60 passed, 0 failures, 0 xfail)
  scripts/          run_benchmarks.py, ab_scaling.py, verify_known_optima.py, plot_results.py
  results/          raw/ per-instance JSON, summaries/, benchmark_results.csv
  docs/             architecture.md, algorithms.md, limitations.md, status.md, results.md
  run_demo.sh        one-command full demonstration
```

## Build / install

```bash
python3 -m venv venv && source venv/bin/activate   # optional
pip install -r requirements.txt
```

No compilation step (pure Python prototype).

## Run the full demo

```bash
./run_demo.sh
```

This runs the test suite, solves an LP and an MILP via the CLI, runs the full
15-instance benchmark suite, measures the equilibration layer A/B, generates
plots, and prints a summary -- all real execution, screenshot-ready.

## Measured results (real execution, see docs/results.md)

Full benchmark suite, `python3 scripts/run_benchmarks.py`:

> **15 instances: 14 OPTIMAL, 1 correctly-detected INFEASIBLE, 0 numerical
> failures, 0 unsolved. 14/15 independently re-verified. 8/8 instances with an
> independently-derived known optimum matched it. Average runtime 0.1189 s.**
>
> Test suite: **60 passed, 0 failed, 0 xfail** (1.79 s).

The 8 known optima are not just hand-derived: `scripts/verify_known_optima.py`
re-derives every one of them in **exact rational arithmetic** (vertex enumeration
by Cramer's rule over `fractions.Fraction` for LPs, exhaustive integer enumeration
for MILPs), sharing no code with the simplex. Result: **8/8 confirmed**, 5 of them
exactly and 3 to within half an ulp -- the latter because a model coefficient like
`1e-4` is not exactly `1/10000` in binary, so the float model's true optimum is not
the round decimal. Details in `docs/results.md`.

### Soundness audit: two unsound optimality claims, found and fixed

A read-only audit of the solver against this repository's own claims found two
paths that reported a result as **proven optimal when optimality had not been
proven**. Presolve could turn an UNBOUNDED model into `OPTIMAL` by inventing a
finite value for a column whose improving bound was infinite; and branch-and-bound
could report `OPTIMAL` with a `0.0000%` gap after discarding a subtree whose LP
relaxation had failed to solve. Neither was catchable by the independent verifier,
because in both cases the reported point *was* feasible and its objective *was*
self-consistent -- only the optimality claim was wrong.

Both are fixed and locked by `tests/test_optimality_claims.py`. **Measured effect
on the 15 benchmark instances: none** -- statuses, objectives, iteration/node
counts, gaps and verification flags are unchanged. Six further findings were
examined and deliberately left unchanged; they are listed with reasoning in
`docs/limitations.md` #9 rather than silently carried.

### Numerical robustness: automatic matrix equilibration

The one substantive improvement made in an earlier development session was
fixing the prototype's top documented numerical limitation: LPs whose coefficients
span many orders of magnitude used to fail spuriously, because the simplex's
absolute pivot tolerance (`1e-7`) is not meaningful on a badly scaled basis.
`sovereign_opt/linalg/scaling.py` now applies iterative geometric-mean row/column
equilibration with power-of-two factors (exact in binary floating point, so
scaling and unscaling introduce no error of their own).

Measured with `python3 scripts/ab_scaling.py` -- all 15 instances, three modes,
best-of-3 wall time, **run back-to-back in one process** so the comparison is not
confounded by machine state:

| Mode | Total runtime | vs off | Solved | Matches known optimum |
|---|---|---|---|---|
| scaling off | 1.7602 s | 1.00x | 13/15 | 6/8 |
| **auto (shipped default)** | **1.7628 s** | **1.00x** | **15/15** | **8/8** |
| scaling always on | 1.9870 s | 0.89x | 15/15 | 8/8 |

Stated precisely: this is a **correctness improvement with no demonstrated runtime
cost**. No speedup is claimed, because none was measured; and no cost is claimed
either, because the `auto`-vs-`off` ratio has landed at 1.01x, 1.00x, 1.00x, 0.99x
and 0.97x across five runs while the two modes execute *identical work* (674
iterations) on the instance that dominates the total. Applying equilibration
unconditionally, by contrast, is genuinely **11-14% slower** -- it perturbs the
pivot sequence on well-scaled models (`refinery_lp_large`: 674 -> 752 iterations) --
which is why it is gated on a magnitude-spread threshold and why that unfavourable
number is published here rather than omitted. With the gate, behaviour on all 13
previously validated instances is bit-identical to before the change.

## Usage

```bash
# Solve an MPS file
python3 -m sovereign_opt.cli path/to/problem.mps

# Solve a synthetic refinery blending LP
python3 -m sovereign_opt.cli --refinery small   # or medium / large

# Solve the integer-batch (MILP) variant
python3 -m sovereign_opt.cli --refinery small --integer

# Run the benchmark suite
python3 scripts/run_benchmarks.py

# Measure the automatic-equilibration layer (off vs auto vs always, same process)
python3 scripts/ab_scaling.py

# Re-derive every declared known optimum in exact rational arithmetic (no simplex)
python3 scripts/verify_known_optima.py

# Measure where solve time actually goes (cProfile + direct instrumentation)
python3 scripts/profile_hotspots.py

# Plot results
python3 scripts/plot_results.py

# Run tests
python3 -m pytest tests/ -v
```

CLI output includes variables/constraints/nonzeros, presolve reduction, LP
relaxation objective (for MILP), branch-and-bound node count / incumbent / best
bound / MIP gap, final status/objective/runtime, and an independent verification
line. It also writes `solution.csv`, `solution.json`, and `solver.log` to
`--outdir`.

## Industrial case study

`sovereign_opt/industrial/refinery.py` generates a **synthetic, clearly-labeled
non-real** crude-blending optimization problem (multiple crudes with availability
and sulfur content, multiple products with demand ranges and quality limits, a
plant capacity constraint), at small/medium/large sizes. See `docs/results.md`
for real solve times at each size.

## Benchmarking

`scripts/run_benchmarks.py` solves every instance in
`sovereign_opt/benchmarks/instances.py` -- a set of 15 hand-built LP/MILP
instances with independently-checked optimal values (re-derived in exact rational
arithmetic by `scripts/verify_known_optima.py`), plus the three refinery sizes.
**This environment has no general internet access**, so no real Netlib or MIPLIB
files were downloaded; nothing in this repository is labeled as Netlib or MIPLIB
data. If you have real `.mps` files, `sovereign_opt/io/mps_format.py` includes a
basic reader you can try, but treat it as unvalidated against real external files
until you check it yourself (see `docs/limitations.md` #6).

## Validation methodology

Every LP and MILP solve is followed by an **independent** re-check, separate from
the solving code path: bounds satisfied, constraints satisfied (recomputed from
the raw coefficients, not reused from the solver's internal state), integrality
satisfied (MILP), and the objective independently recomputed from the reported
variable values and compared to the reported objective. A result is only reported
as `verified_feasible: true` if all of these pass. See `verify_lp_solution()` in
`lp/simplex.py` and `_verify_milp()` in `milp/branch_and_bound.py`.

**This check is enforced, not advisory.** A solution that fails it is reported as
`NUMERICAL_FAILURE`, never as `OPTIMAL` -- so `status == OPTIMAL` always implies
independent verification passed. That contract is locked by
`tests/test_verification_contract.py`, and it exists because the opposite was
found happening: see `docs/limitations.md` #1b for the reproducer.

**A second, separate contract covers the optimality claim itself:** no path may
report `OPTIMAL` (or a 0% MIP gap, or `INFEASIBLE`) unless optimality or
infeasibility was actually proven. This is not implied by the check above --
a point can be perfectly feasible and self-consistent while the *claim* that it is
optimal is false, which is exactly how both defects in `docs/limitations.md` #1c
slipped past verification. Locked by `tests/test_optimality_claims.py`.

A third layer sits outside the solver entirely: `scripts/verify_known_optima.py`
re-derives the benchmark library's declared optima in exact rational arithmetic
with no simplex involved, so the "8/8 matched known optimum" figure rests on
repository evidence rather than on hand-derivation.
`tests/test_known_optima_exact.py` checks both the declared constants and the
solver's own objective against that oracle.

## Algorithms implemented

See `docs/algorithms.md` for full detail. Summary: two-phase revised simplex
(Bland's rule, from-scratch Gaussian-elimination basis solves), reversible basic
presolve, automatic geometric-mean matrix equilibration, branch-and-bound MILP
(most-fractional branching) on top of the LP solver, basic MPS I/O.

## Algorithms NOT implemented

Sparse LU factorization/updates, native bounded-variable simplex, dual simplex /
warm-starting, pseudocost/strong branching, cutting planes, primal heuristics,
interior-point methods, QP/MIQP/NLP/MINLP, GPU acceleration, parallel
branch-and-bound. Full list with reasoning in `docs/algorithms.md`.

## Known limitations (measured, not estimated)

Full detail in `docs/limitations.md`. Headlines:
- Dense, non-LU-updated simplex: validated to roughly dozens-to-~100 variables in
  reasonable time (96-variable refinery instance: 1.67 s); large-scale (thousands
  to millions of variables, the PS's ultimate target) is **not established**.
  Profiling (`scripts/profile_hotspots.py`, two independent methods agreeing to
  0.3pp) puts **~98% of solve time inside our own Gaussian-elimination basis
  solves** -- so the bottleneck is measured, not guessed, and the first fix is
  sparse LU with factorization updates on the CPU.
- The equilibration layer is gated on a pre-solve magnitude-spread heuristic; a
  model that only becomes ill-conditioned mid-search would not trigger it.
- Naive branch-and-bound can hit its node limit before proving optimality on
  wide-integer-domain instances (one measured case: 0.49% gap after 5000 nodes).
- Six audited-but-unchanged issues, including `ObjSense.MAX` being accepted by the
  API but never honored, and the `lp_mixed_units_ill_conditioned` instance not
  actually exercising the equilibration path despite its name
  (`docs/limitations.md` #9).

## Roadmap after SIH shortlisting

See `docs/status.md`: sparse LU basis solves, native bounded-variable simplex,
dual simplex/warm-starting, cutting planes/pseudocost branching, a C++17 port of
the now-validated algorithms, QP/interior-point support, and real Netlib/MIPLIB
validation plus an actually-run comparison against an open-source reference
solver once network access and time permit.

## Why this qualifies as a from-scratch sovereign optimization prototype

Every numerical algorithm that solves the optimization problem -- the basis
linear-system solves, the simplex pivoting logic, the branch-and-bound tree
search -- is implemented in this repository's own code, not delegated to any
external LP/MILP/QP library. General-purpose libraries used (numpy, matplotlib,
pytest) do array storage, plotting, and test orchestration respectively; none of
them solve the optimization problem. The prototype is intentionally narrower than
the PS's full production target (documented above and in `docs/limitations.md`),
but every claim of "implemented" in this README is backed by a passing test or a
real, reproducible run recorded in `docs/results.md`.
