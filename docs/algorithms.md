# Algorithms

## Implemented (genuinely, and tested -- see docs/results.md for real run output)

- **Two-phase revised simplex** (`lp/simplex.py`)
  - Phase 1: minimizes sum of artificial variables from an all-artificial start basis
    (uniformly added to every row, sign chosen for initial feasibility)
  - Phase 2: minimizes the true objective, artificials barred from re-entering
  - Reduced costs computed via `y^T B = c_B` (a genuine "revised" formulation --
    reduced costs are NOT read off a full tableau)
  - Entering/leaving variable selection: **Bland's rule** (smallest index), chosen
    for its cycling-freedom guarantee over Dantzig's rule's typically-fewer iterations
  - Every basis solve (`B x = b` and `B^T y = c_B`) goes through our own Gaussian
    elimination with partial pivoting (`linalg/gauss.py`) -- rebuilt from scratch
    every iteration (no LU-update / product-form-of-inverse acceleration)
  - Status handling: OPTIMAL, INFEASIBLE, UNBOUNDED, ITERATION_LIMIT,
    NUMERICAL_FAILURE (raised, never silently swallowed, when a basis solve hits a
    near-singular pivot)
  - Variable bounds: lower bounds via a `y = x - lb` shift; upper bounds via an
    explicit extra `<=` row (NOT native bounded-variable simplex -- see limitations)

- **Basic reversible presolve** (`presolve/presolve.py`)
  - Fixed-variable substitution (`lb == ub`)
  - Empty-row detection + feasibility check
  - Empty-column fixing (fixed at the objective-optimal bound)
  - Singleton-row -> bound-tightening conversion
  - Direct infeasibility detection (`lb > ub`)
  - Every reduction is logged in a `PresolveLog` and reversed by `postsolve_values()`;
    the true objective is recomputed on the original model post-postsolve (this
    prototype originally had a bug where it trusted the reduced model's objective
    directly -- caught by testing, fixed, see docs/status.md)

- **Branch-and-bound MILP** (`milp/branch_and_bound.py`), built entirely on the LP
  stack above (no external MILP/LP solver used anywhere):
  - LP relaxation at the root and at every node (via the same presolve+simplex path)
  - Integer feasibility checking with a fractionality tolerance
  - **Most-fractional-variable branching** (a simple, defensible default; not
    pseudocost or strong branching)
  - Depth-first node stack (plain Python list, LIFO) with bound-based pruning
    against the current incumbent
  - Incumbent tracking, MIP gap calculation
  - Node-limit and time-limit termination criteria
  - Independent post-hoc verification of the incumbent (bounds, integrality,
    constraint satisfaction, objective recomputation)

- **Automatic matrix equilibration** (`linalg/scaling.py`)
  - Iterative **geometric-mean row/column scaling**: each pass replaces row `i` by
    `r_i = 1/sqrt(max|a_ij| * min|a_ij|)` over its nonzeros, then does the same by
    column, repeating while the magnitude spread keeps improving (default: up to 20
    passes, stop when a pass improves the spread by less than 10%)
  - All factors are **rounded to the nearest power of two**, so scaling and
    unscaling are exact in binary floating point and introduce no rounding error of
    their own
  - One uniform **objective (cost) scale**, `1/geomean(|c_j|)` also rounded to a
    power of two, so that the *absolute* reduced-cost tolerance `1e-7` means the
    same thing regardless of the objective's units
  - **Threshold-gated** (`DEFAULT_SCALING_THRESHOLD = 1e4`): a model whose
    magnitude spread is below the threshold is not touched at all, so previously
    validated instances keep a bit-identical numerical path. The threshold is
    derived from the pivot floor (`1e-7`), not fitted to the benchmark set
  - **Safety net**: if a round of equilibration makes the spread worse, identity
    factors are returned instead
  - Fully reversible: column factors are undone on the recovered solution
    (`x_j = d_j * x_hat_j + lb_j`) and the cost factor on the objective, and the
    result is then re-verified against the ORIGINAL model
  - Why this and not a scale-aware pivot tolerance: the tolerance variant was
    implemented and **measured worse**, so the matrix is scaled instead of the test

- **Fail-loud verification contract** (`lp/simplex.py`, `lp/orchestrator.py`,
  `milp/branch_and_bound.py`)
  - Every reported solution is independently re-checked against the ORIGINAL model
    (bounds, every constraint, objective recomputed by a different arithmetic path
    than the simplex used)
  - If that check fails, the status is downgraded to `NUMERICAL_FAILURE` with a
    `REJECTED (failed independent verification)` message -- `status == OPTIMAL`
    therefore implies `verified_feasible == True` in all layers

- **Soundness contract on the optimality claim** (`presolve/presolve.py`,
  `milp/branch_and_bound.py`) -- a *separate* invariant from the one above:
  no path may report `OPTIMAL`, a `0%` MIP gap, or `INFEASIBLE` unless
  optimality/infeasibility was actually proven
  - The verification contract cannot enforce this. A point can be feasible and its
    objective self-consistent while the claim that it is *optimal* is false; both
    defects in docs/limitations.md #1c passed verification for exactly that reason
  - **Presolve**: an empty column is fixed at its improving bound only when that
    bound is finite. If it is infinite the column stays in the reduced model, so
    the simplex's own unboundedness test decides -- presolve never invents a
    finite value that would convert `UNBOUNDED` into a wrong `OPTIMAL`
  - **Branch-and-bound**: only `INFEASIBLE` is a sound prune (a proven-empty
    subtree). A node whose relaxation returns `UNBOUNDED` / `ITERATION_LIMIT` /
    `NUMERICAL_FAILURE` was neither explored nor excluded, so it is counted in
    `MILPResult.abandoned_nodes`; a non-zero count forfeits both the `OPTIMAL` and
    the `INFEASIBLE` claim, drops the bound back to the root relaxation (the only
    one still known valid), and makes the CLI print a warning
  - Locked by `tests/test_optimality_claims.py`

- **Simplex-independent optimality oracle** (`scripts/verify_known_optima.py`) --
  not part of the solver, and deliberately so: it re-derives the benchmark
  library's declared optima with no simplex and no floating point, using exact
  rational arithmetic (`fractions.Fraction`)
  - LP: all n-subsets of the constraint/bound hyperplanes, solved exactly by
    Cramer's rule, infeasible and singular candidates discarded, exact minimum over
    the surviving vertices; an artificial box makes enumeration well-posed and the
    script refuses to certify an instance if that box binds at the optimum
  - MILP: exhaustive enumeration of the integer box
  - Result: 8/8 declared optima confirmed, 5 exactly and 3 to within half an ulp
    (the float model's true optimum is not the round decimal, because `1e-4` is not
    exactly `1/10000` in binary). Locked by `tests/test_known_optima_exact.py`

- **Basic free-format MPS I/O** (`io/mps_format.py`) -- reader supports ROWS/COLUMNS
  (incl. INTORG/INTEND integer markers)/RHS/BOUNDS/ENDATA; writer round-trips our
  own instances (tested).

## NOT implemented (stated plainly, per the factuality requirement)

- Sparse LU factorization / product-form-of-inverse / any warm-started or updated
  basis solve -- every iteration rebuilds and re-solves the dense basis matrix from
  scratch via Gaussian elimination. `sparse/matrix.py` provides sparse *storage*
  only; it is not wired into the simplex basis solve.
- Native bounded-variable (upper-bound-aware) simplex -- upper bounds are explicit
  rows, which is correct but less efficient and inflates the row count.
- Dual simplex / warm-starting between B&B nodes -- every node's LP relaxation is
  solved completely from scratch.
- Pseudocost or strong branching, primal heuristics, cutting planes (Gomory,
  cover cuts, etc.) -- listed in the PS as "if time permits"; not attempted in
  this prototype given the time budget.
- Interior-point methods, QP/MIQP, NLP/MINLP -- out of scope for this prototype
  (PS explicitly frames LP/MILP as the initial focus).
- GPU acceleration, multi-core parallel branch-and-bound.
- Free (unbounded-below, `lb = -inf`) variables -- `_StdForm` raises
  `NotImplementedError` rather than silently mishandling them.
- Full MPS-spec coverage (RANGES section, SOS constraints, comment-field edge cases).

See docs/limitations.md for measured (not estimated) consequences of these gaps.
