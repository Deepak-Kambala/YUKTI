# Status

Last updated: end of this build session (see docs/results.md for the real run that
backs every number below).

## Implemented and tested
- Problem representation (`core/model.py`)
- Sparse storage (`sparse/matrix.py`) -- storage only, not wired into simplex
- From-scratch Gaussian elimination (`linalg/gauss.py`)
- Two-phase revised simplex (`lp/simplex.py`) -- OPTIMAL/INFEASIBLE/UNBOUNDED/
  NUMERICAL_FAILURE all exercised by tests
- Automatic matrix equilibration (`linalg/scaling.py`) -- geometric-mean row/column
  scaling with power-of-two factors, threshold-gated so well-scaled models are left
  bit-identical to the unscaled path
- Fail-loud verification contract -- `status == OPTIMAL` implies the solution passed
  independent re-verification against the ORIGINAL model, in every solver layer
- Soundness contract -- no path reports `OPTIMAL`, a 0% MIP gap, or `INFEASIBLE`
  unless optimality/infeasibility was actually proven (separate from the above:
  a feasible, self-consistent point can still carry a false optimality claim)
- Reversible presolve + orchestrator (`presolve/`, `lp/orchestrator.py`)
- Branch-and-bound MILP (`milp/branch_and_bound.py`)
- Basic MPS I/O (`io/mps_format.py`), round-trip tested (LP + MILP w/ int markers)
- Synthetic refinery case study generator (`industrial/refinery.py`)
- Hand-built benchmark instance library with independently-checked optima
  (`benchmarks/instances.py`), including three ill-conditioned LPs (spread 1e8/1e9/1e12)
- Exact-rational optimality oracle (`scripts/verify_known_optima.py`) -- re-derives
  all 8 declared known optima with no simplex and no floating point; 8/8 confirmed
- CLI (`cli.py`), benchmark runner (`scripts/run_benchmarks.py`), scaling A/B
  (`scripts/ab_scaling.py`), plotting (`scripts/plot_results.py`)
- 60 pytest tests, all passing, 0 xfail (1.79 s)

## Fixed in the soundness audit (most recent session)
1. **Presolve turned UNBOUNDED into a wrong OPTIMAL.** An empty column whose
   improving bound was infinite was fixed at an invented finite value, so
   `min -x, x in [0,inf)` in no row returned `OPTIMAL objective=1.0
   verified_feasible=True` with presolve on and `UNBOUNDED` with presolve off.
   Such columns are now left in the reduced model for the simplex's own
   unboundedness test. Reductions with a finite improving bound are unchanged.
2. **Branch-and-bound claimed a 0.0000% gap over an unexplored tree.** Nodes whose
   LP relaxation did not solve were pruned exactly like proven-infeasible ones.
   They are now counted (`MILPResult.abandoned_nodes`) and forfeit the optimality
   (and infeasibility) claim; the CLI warns when the count is non-zero.
   Injected-failure reproducer: `OPTIMAL gap=0.0000` ->
   `FEASIBLE_NOT_PROVEN_OPTIMAL gap=0.0568`.

Measured effect of both fixes on the 15-instance benchmark suite: **none** --
every status, objective, iteration/node count, gap and verification flag is
unchanged. Tests went 37 -> 60 passing with no pre-existing test modified.

## Fixed in the preceding session (was previously a disclosed failure)
1. **Ill-conditioning.** Poorly-scaled coefficients no longer trigger spurious
   NUMERICAL_FAILURE. Measured: with scaling off the suite solves 13/15 and matches
   6/8 known optima; with the shipped default it solves 15/15 and matches 8/8, with
   no demonstrated runtime cost (`scripts/ab_scaling.py`). Applying scaling
   unconditionally instead costs 11-14%, which is why it is threshold-gated.
2. **Silent wrong answer.** A result that failed independent verification was still
   reported with `status=OPTIMAL` (reproducer: `lp_ill_conditioned_1e12` with scaling
   off returned objective -1e9 against a true optimum of -1e7). All layers now
   downgrade to NUMERICAL_FAILURE; locked by `tests/test_verification_contract.py`.

## Known failures (see docs/limitations.md for full detail)
1. Non-discretized-integer MILP instances with wide integer domains can hit the
   node limit before proving optimality (measured: 0.49% gap after 5000 nodes /
   13.69s on one refinery variant).
2. Dense O(m^3)-per-iteration simplex limits validated problem size to roughly
   dozens to ~100 variables in reasonable time; large-scale performance (the PS's
   ultimate target) is not established.
3. The scaling threshold is a heuristic on the pre-solve matrix spread; a model that
   only becomes ill-conditioned during branch-and-bound bound tightening would not
   trigger it. Not observed in the suite, not excluded.
4. Free variables (`lb = -inf`) raise NotImplementedError rather than being solved.
5. `ObjSense.MAX` is accepted by `Model.set_objective` but never honored -- the
   solver always minimizes. No shipped model uses it (every `set_objective` call in
   the repository passes `ObjSense.MIN`), so no reported result is affected, but it
   is a public-API path that would silently return a minimum. Audited and
   deliberately left unchanged mid-audit; see docs/limitations.md #9d.
6. Five further audited-but-unchanged items (mixed-units instance not exercising the
   scaling path, the LP `Gap` column being asserted rather than measured, the
   absolute ratio-test tie-break tolerance, an unclamped negative basic value, and
   the absolute Phase-1 infeasibility threshold): docs/limitations.md #9.

## Next task if development continued
- Decide `ObjSense.MAX`'s behaviour (negate internally, or reject at the door) and
  implement it -- currently accepted and ignored; see known failure #5.
- Add a reference-solver comparison script (only once a reference solver, e.g.
  a locally-installed open-source one, is actually available -- not fabricated).
- Try to source real Netlib/MIPLIB files in an environment with internet access
  and validate `io/mps_format.py`'s reader against them.
- Sparse LU factorization with update (product-form-of-inverse or similar) to
  address known failure #2 above -- the highest-leverage next step for scaling.
- Native bounded-variable simplex to remove the explicit-upper-bound-row
  inefficiency.

## Roadmap toward the full SIH PS scope
1. Sparse LU-based basis solve (replaces dense Gaussian elimination as the
   default; the Gaussian-elimination path can remain as a small-problem/
   verification fallback).
2. Native bounded-variable simplex.
3. Dual simplex + warm-starting for branch-and-bound nodes.
4. Pseudocost branching, primal heuristics, basic cutting planes.
5. A genuine C++17 port of the now-validated algorithm designs, with CMake +
   GoogleTest, once the Python prototype's correctness is the accepted baseline
   to test the port against.
6. Interior-point method for LP/QP; QP support; eventually MIQP/NLP/MINLP per
   the PS's stated extension path.
7. Multi-core parallel branch-and-bound; GPU acceleration investigation (PS
   frames this as "where it provides measurable benefit" -- i.e., only after
   profiling shows it would help).
8. Real Netlib/MIPLIB/Mittelmann benchmark validation once file access is
   available, plus an honest, actually-run comparison against at least one
   open-source reference solver as the PS requests.
