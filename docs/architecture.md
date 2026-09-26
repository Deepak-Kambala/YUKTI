# Architecture

## Layout

```
sovereign-opt/
  sovereign_opt/
    core/model.py           Problem representation (Variable, Constraint, Model)
    sparse/matrix.py        From-scratch CSR sparse storage (storage only; see limitations)
    linalg/gauss.py         From-scratch Gaussian elimination (basis solves for simplex)
    linalg/scaling.py       Geometric-mean row/col equilibration (threshold-gated)
    presolve/presolve.py    Reversible presolve reductions
    lp/simplex.py           Two-phase revised simplex
    lp/orchestrator.py      presolve -> solve -> postsolve -> reverify pipeline
    milp/branch_and_bound.py  Branch-and-bound MILP on top of lp/
    io/mps_format.py        Basic free-format MPS reader/writer
    industrial/refinery.py  Synthetic refinery crude-blending instance generator
    benchmarks/instances.py Hand-built LP/MILP benchmark instances with known optima
    cli.py                  Command-line entry point
  tests/                     pytest unit/integration tests
  scripts/                   run_benchmarks.py, ab_scaling.py, plot_results.py
  results/                   raw/ (per-instance JSON), summaries/, benchmark_results.csv
  docs/                      this file + algorithms.md, limitations.md, status.md, results.md
```

## Data flow (LP)

```
Model --> presolve() --> reduced Model --> solve_lp()
                                             |
                                             +-- auto_scaling() [if spread > 1e4]
                                             +-- two-phase simplex (scaled space)
                                             +-- unscale solution + objective
       --> postsolve_values() --> recompute objective on ORIGINAL model
       --> verify_lp_solution() [independent recheck]
       --> status downgraded to NUMERICAL_FAILURE if that recheck fails
```

## Data flow (MILP)

```
Model --> solve_milp()
            |
            +--> root: solve_lp_with_presolve(model)  [LP relaxation via the same LP stack]
            |
            +--> branch-and-bound stack of (lb_overrides, ub_overrides)
                   each node: apply bounds -> solve_lp_with_presolve(node_model)
                   -> integer feasibility check -> branch or prune or accept incumbent
            +--> _verify_milp() independent recheck of the final incumbent
```

## Why Python instead of C++ for this prototype

The PS's preferred stack is C++17 + CMake + GoogleTest. Given the prototype-stage time
budget and the requirement that every algorithm actually run, be tested, and be
independently verified before being reported, this prototype was built in Python:

- Faster iteration between "write algorithm -> run -> see it fail -> fix" cycles, which
  matters more at this stage than raw performance.
- numpy is used ONLY for array storage/elementwise arithmetic, never for solving --
  the actual linear-algebra solve inside simplex (`linalg/gauss.py`) is hand-written
  Gaussian elimination, not `numpy.linalg.solve`. This preserves the "from-scratch
  solver core" requirement while accepting Python-level constant-factor overhead.
- A C++ port of exactly this design (same algorithms, same module boundaries) is
  listed in the roadmap in docs/status.md and would be the natural next step once
  the algorithms are validated, which is what this prototype accomplishes.

This is a real scope/time tradeoff, stated plainly rather than silently -- see
docs/limitations.md for what it costs in performance (measured, not estimated).
