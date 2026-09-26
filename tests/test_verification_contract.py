"""
Tests for the fail-loud contract:

    "Do not silently return an answer when numerical verification fails."

These exist because a real bug was found by measurement: with equilibration
disabled, `lp_ill_conditioned_1e12` returned status=OPTIMAL with objective
-1e9 when the hand-derived optimum is -1e7. The independent verifier caught
it (verified_feasible=False) but the STATUS still claimed OPTIMAL. Every
solver layer now downgrades such a result to NUMERICAL_FAILURE.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sovereign_opt.core.model import Model, Sense, ObjSense
from sovereign_opt.lp.simplex import solve_lp, LPStatus
from sovereign_opt.lp.orchestrator import solve_lp_with_presolve
from sovereign_opt.benchmarks.instances import get_instances


def _inst(name):
    return next(i for i in get_instances() if i.name == name)


def test_unverified_result_is_never_reported_optimal_lp():
    """The reproducer: scaling off on a spread-1e12 model produces a wrong
    objective; the solver must refuse to call it OPTIMAL."""
    m = _inst("lp_ill_conditioned_1e12").build()
    r = solve_lp(m, use_scaling=False)
    if not r.verified_feasible:
        assert r.status != LPStatus.OPTIMAL
        assert "REJECTED" in r.verification_message
    else:
        # if it ever does verify, the objective must be the hand-derived one
        assert abs(r.objective - (-1e7)) < 1e-6 * 1e7


def test_unverified_result_is_never_reported_optimal_orchestrator():
    m = _inst("lp_ill_conditioned_1e12").build()
    rep = solve_lp_with_presolve(m, use_scaling=False)
    assert (rep.status == LPStatus.OPTIMAL) == rep.verified_feasible


def test_optimal_always_implies_verified_across_benchmark_set():
    """Contract over the whole instance library: status OPTIMAL => verified."""
    for inst in get_instances():
        model = inst.build()
        if model.is_milp():
            continue
        rep = solve_lp_with_presolve(model)
        if rep.status == LPStatus.OPTIMAL:
            assert rep.verified_feasible, f"{inst.name}: OPTIMAL but unverified"


def test_known_optima_are_matched_where_declared():
    """Every LP instance with a hand-derived optimum must reproduce it."""
    for inst in get_instances():
        if inst.known_optimal is None:
            continue
        model = inst.build()
        if model.is_milp():
            continue
        rep = solve_lp_with_presolve(model)
        assert rep.status == LPStatus.OPTIMAL, f"{inst.name}: {rep.status}"
        assert abs(rep.objective - inst.known_optimal) < 1e-6 * max(1.0, abs(inst.known_optimal)), \
            f"{inst.name}: got {rep.objective}, known {inst.known_optimal}"
