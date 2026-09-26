"""
The declared `known_optimal` values must agree with an oracle that shares no
code with the simplex.

`scripts/run_benchmarks.py` reports "matched known optimum: 8/8", which is only
meaningful if those 8 constants are themselves right. They were originally
hand-derived, and one of them was hand-derived WRONG (see docs/results.md). This
locks them against `scripts/verify_known_optima.py`, which re-derives each one by
exact rational vertex / integer enumeration -- no simplex, no floating point.

Cheap by construction: the largest enumeration in the library is 32 integer
points or C(8,3)=56 vertex candidates.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest

from sovereign_opt.benchmarks.instances import get_instances
from sovereign_opt.lp.orchestrator import solve_lp_with_presolve
from sovereign_opt.lp.simplex import LPStatus
from sovereign_opt.milp.branch_and_bound import solve_milp, MILPStatus
from verify_known_optima import exact_lp_optimum, exact_milp_optimum

_WITH_KNOWN = [i for i in get_instances() if i.known_optimal is not None]


def _oracle(inst):
    if inst.problem_type == "MILP":
        opt, _, _ = exact_milp_optimum(inst.build())
        return opt, True
    opt, _, _, certified_bounded = exact_lp_optimum(inst.build())
    return opt, certified_bounded


@pytest.mark.parametrize("inst", _WITH_KNOWN, ids=lambda i: i.name)
def test_declared_known_optimum_matches_exact_oracle(inst):
    exact, certified = _oracle(inst)
    assert certified, f"{inst.name}: artificial bound active; optimum not certified bounded"
    # Model coefficients are floats, so the exact optimum of the float model is
    # not always the round decimal written in the instance (e.g. 1e-4 is not
    # exactly 1/10000). The meaningful contract is that the declared value is
    # the correctly-rounded double of the exact optimum.
    assert float(exact) == inst.known_optimal, (
        f"{inst.name}: declared {inst.known_optimal}, exact optimum {exact} "
        f"(-> {float(exact)})"
    )


@pytest.mark.parametrize("inst", _WITH_KNOWN, ids=lambda i: i.name)
def test_solver_matches_exact_oracle(inst):
    """The solver itself, checked against arithmetic it does not share."""
    exact, certified = _oracle(inst)
    assert certified
    model = inst.build()
    if inst.problem_type == "MILP":
        r = solve_milp(model)
        assert r.status == MILPStatus.OPTIMAL, f"{inst.name}: {r.status.value}"
    else:
        r = solve_lp_with_presolve(model)
        assert r.status == LPStatus.OPTIMAL, f"{inst.name}: {r.status.value}"
    assert r.verified_feasible
    target = float(exact)
    assert abs(r.objective - target) <= 1e-6 * max(1.0, abs(target)), (
        f"{inst.name}: solver {r.objective}, exact oracle {target}"
    )
