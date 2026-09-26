"""
No code path may report OPTIMAL (or a 0% MIP gap, or INFEASIBLE) unless
optimality/infeasibility was actually proven.

This is a separate contract from tests/test_verification_contract.py. That one
checks `status == OPTIMAL => the reported point is feasible and its objective is
self-consistent`. It cannot catch the failures below, because in both of them the
reported point IS feasible and its objective IS self-consistent -- what is wrong
is the *optimality claim* attached to it. Both failures were found by audit and
are reproduced here.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sovereign_opt.core.model import Model, Sense, ObjSense, VarType, INF
from sovereign_opt.lp.orchestrator import solve_lp_with_presolve
from sovereign_opt.lp.simplex import LPStatus
from sovereign_opt.presolve.presolve import presolve
import sovereign_opt.milp.branch_and_bound as bnb
from sovereign_opt.milp.branch_and_bound import solve_milp, MILPStatus


# --------------------------------------------------------------------------
# 1. Presolve must not invent a finite value for an unbounded empty column.
# --------------------------------------------------------------------------

def _unbounded_empty_column_model():
    """min -x + z  with x in [0, inf) appearing in NO constraint => UNBOUNDED."""
    m = Model("unbounded_empty_col")
    m.add_variable("x", lb=0.0, ub=INF)
    m.add_variable("z", lb=0.0, ub=5.0)
    m.add_constraint("c1", {"z": 1.0}, Sense.GE, 1.0)
    m.set_objective({"x": -1.0, "z": 1.0}, ObjSense.MIN)
    return m


def test_presolve_does_not_hide_unboundedness():
    """Regression: presolve used to fix x at 0.0 and report OPTIMAL obj=1.0."""
    m = _unbounded_empty_column_model()
    rep = solve_lp_with_presolve(m, use_presolve=True)
    assert rep.status == LPStatus.UNBOUNDED, (
        f"presolve reported {rep.status.value} (obj={rep.objective}) for an "
        "unbounded model"
    )


def test_presolve_agrees_with_no_presolve_on_unbounded_model():
    """Presolve must not change the answer -- that is the whole contract."""
    m = _unbounded_empty_column_model()
    on = solve_lp_with_presolve(m, use_presolve=True)
    off = solve_lp_with_presolve(m, use_presolve=False)
    assert on.status == off.status == LPStatus.UNBOUNDED


def test_empty_column_with_finite_improving_bound_is_still_reduced():
    """The reduction itself must be kept where it was always correct."""
    m = Model("bounded_empty_col")
    m.add_variable("x", lb=0.0, ub=7.0)          # empty column, cost < 0 -> ub
    m.add_variable("y", lb=0.0, ub=4.0)          # empty column, cost > 0 -> lb
    m.add_variable("z", lb=0.0, ub=5.0)
    m.add_constraint("c1", {"z": 1.0}, Sense.GE, 1.0)
    m.set_objective({"x": -2.0, "y": 3.0, "z": 1.0}, ObjSense.MIN)

    reduced, log = presolve(m)
    assert "x" not in reduced.variables and "y" not in reduced.variables

    rep = solve_lp_with_presolve(m)
    assert rep.status == LPStatus.OPTIMAL
    assert abs(rep.values["x"] - 7.0) < 1e-9     # driven to ub
    assert abs(rep.values["y"] - 0.0) < 1e-9     # driven to lb
    assert abs(rep.objective - (-2.0 * 7.0 + 1.0)) < 1e-9


# --------------------------------------------------------------------------
# 2. Branch-and-bound must not claim proven optimality over an unexplored tree.
# --------------------------------------------------------------------------

def _small_milp():
    m = Model("bnb_soundness")
    m.add_variable("a", lb=0.0, ub=10.0, vtype=VarType.INTEGER)
    m.add_variable("b", lb=0.0, ub=10.0, vtype=VarType.INTEGER)
    m.add_constraint("c1", {"a": 6.0, "b": 4.0}, Sense.LE, 25.0)
    m.add_constraint("c2", {"a": 1.0, "b": 2.0}, Sense.LE, 9.0)
    m.set_objective({"a": -5.0, "b": -4.0}, ObjSense.MIN)
    return m


def test_clean_branch_and_bound_still_proves_optimality():
    r = solve_milp(_small_milp())
    assert r.status == MILPStatus.OPTIMAL
    assert r.abandoned_nodes == 0
    assert r.mip_gap == 0.0
    assert abs(r.objective - (-22.0)) < 1e-9


def _run_with_failing_node(model, fail_on_call):
    """Solve `model`, forcing the `fail_on_call`-th node LP to fail numerically.

    No instance in the current benchmark library produces a failing node LP, so
    the failure is injected: that is the only way to test the bookkeeping that
    decides whether optimality may be claimed. The injection is reverted in a
    `finally` so it cannot leak into other tests.
    """
    real = bnb.solve_lp_with_presolve
    calls = {"n": 0}

    def flaky(m, **kw):
        calls["n"] += 1
        rep = real(m, **kw)
        if calls["n"] == fail_on_call and rep.status == LPStatus.OPTIMAL:
            rep.status = LPStatus.NUMERICAL_FAILURE
            rep.verified_feasible = False
            rep.verification_message = "injected numerical failure (test)"
        return rep

    bnb.solve_lp_with_presolve = flaky
    try:
        return solve_milp(model)
    finally:
        bnb.solve_lp_with_presolve = real


def test_failed_node_forfeits_the_optimality_claim():
    """Regression: a failed node LP used to be pruned exactly like an
    INFEASIBLE one, and the search still reported OPTIMAL with a 0.0000% gap."""
    r = _run_with_failing_node(_small_milp(), fail_on_call=3)
    assert r.abandoned_nodes >= 1
    assert r.status != MILPStatus.OPTIMAL
    assert r.status == MILPStatus.FEASIBLE
    assert r.mip_gap is not None and r.mip_gap > 0.0, (
        "a tree with an unexplored subtree must not report a zero gap"
    )


def test_failed_root_child_without_incumbent_is_not_called_infeasible():
    """With no incumbent AND an abandoned subtree, INFEASIBLE is not provable."""
    r = _run_with_failing_node(_small_milp(), fail_on_call=2)
    if r.abandoned_nodes and r.objective is None:
        assert r.status == MILPStatus.NUMERICAL_FAILURE
    else:
        # an incumbent survived; then it may only be reported as unproven
        assert r.status != MILPStatus.OPTIMAL


def test_infeasible_node_is_still_a_sound_prune():
    """INFEASIBLE nodes are proven-empty subtrees and must NOT count as
    abandoned -- otherwise every normal MILP would lose its optimality claim."""
    m = _small_milp()
    m.add_constraint("c3", {"a": 1.0}, Sense.GE, 1.0)
    r = solve_milp(m)
    assert r.status == MILPStatus.OPTIMAL
    assert r.abandoned_nodes == 0
