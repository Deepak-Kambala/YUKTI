"""Unit tests for the revised simplex LP solver."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from sovereign_opt.core.model import Model, Sense, ObjSense, VarType
from sovereign_opt.lp.simplex import solve_lp, LPStatus


def test_simple_max_via_min():
    m = Model("t")
    m.add_variable("x", lb=0)
    m.add_variable("y", lb=0)
    m.add_constraint("c1", {"x": 1}, Sense.LE, 4)
    m.add_constraint("c2", {"y": 2}, Sense.LE, 12)
    m.add_constraint("c3", {"x": 3, "y": 2}, Sense.LE, 18)
    m.set_objective({"x": -3, "y": -5}, ObjSense.MIN)
    r = solve_lp(m)
    assert r.status == LPStatus.OPTIMAL
    assert abs(r.objective - (-36.0)) < 1e-6
    assert abs(r.values["x"] - 2.0) < 1e-6
    assert abs(r.values["y"] - 6.0) < 1e-6
    assert r.verified_feasible


def test_infeasible():
    m = Model("t")
    m.add_variable("x", lb=0)
    m.add_constraint("c1", {"x": 1}, Sense.LE, 1)
    m.add_constraint("c2", {"x": 1}, Sense.GE, 5)
    m.set_objective({"x": 1}, ObjSense.MIN)
    r = solve_lp(m)
    assert r.status == LPStatus.INFEASIBLE


def test_unbounded():
    m = Model("t")
    m.add_variable("x", lb=0)
    m.add_constraint("c1", {"x": 0}, Sense.LE, 100)
    m.set_objective({"x": -1}, ObjSense.MIN)
    r = solve_lp(m)
    assert r.status == LPStatus.UNBOUNDED


def test_equality_constraint():
    m = Model("t")
    m.add_variable("x", lb=0)
    m.add_variable("y", lb=0)
    m.add_constraint("c1", {"x": 1, "y": 1}, Sense.EQ, 10)
    m.set_objective({"x": 1, "y": 2}, ObjSense.MIN)
    r = solve_lp(m)
    assert r.status == LPStatus.OPTIMAL
    assert abs(r.objective - 10.0) < 1e-6
    assert abs(r.values["x"] - 10.0) < 1e-6
    assert abs(r.values["y"] - 0.0) < 1e-6


def test_nonzero_lower_bound_shift():
    # x in [5,20], minimize x s.t. x >= 5 implicitly via bound
    m = Model("t")
    m.add_variable("x", lb=5, ub=20)
    m.add_constraint("dummy", {"x": 0}, Sense.LE, 1000)
    m.set_objective({"x": 1}, ObjSense.MIN)
    r = solve_lp(m)
    assert r.status == LPStatus.OPTIMAL
    assert abs(r.objective - 5.0) < 1e-6


def test_degenerate_ties():
    # Degenerate LP: multiple constraints binding at same vertex.
    # minimize -x - y  s.t. x<=2, y<=2, x+y<=4, x,y>=0  (degenerate at (2,2))
    m = Model("t")
    m.add_variable("x", lb=0, ub=2)
    m.add_variable("y", lb=0, ub=2)
    m.add_constraint("c1", {"x": 1, "y": 1}, Sense.LE, 4)
    m.set_objective({"x": -1, "y": -1}, ObjSense.MIN)
    r = solve_lp(m)
    assert r.status == LPStatus.OPTIMAL
    assert abs(r.objective - (-4.0)) < 1e-6
    assert r.verified_feasible


def test_poorly_scaled_coefficients():
    """
    FORMERLY A DOCUMENTED FAILURE (xfail), now fixed by automatic equilibration
    in linalg/scaling.py. Coefficients span 1e-4..1e4 (magnitude spread 1e8).
    Hand-derived optimum: x is worth 1/1e-4 = 1e4 objective units per unit of
    constraint capacity versus y's 1e-3/1e4 = 1e-7, so y stays at 0 and x binds
    the constraint at 50/1e-4 = 5e5 (below its own ub of 1e6) -> objective -5e5.
    """
    m = Model("t")
    m.add_variable("x", lb=0, ub=1e6)
    m.add_variable("y", lb=0, ub=1e-3)
    m.add_constraint("c1", {"x": 1e-4, "y": 1e4}, Sense.LE, 50)
    m.set_objective({"x": -1, "y": -1e-3}, ObjSense.MIN)
    r = solve_lp(m)
    assert r.status == LPStatus.OPTIMAL
    assert r.verified_feasible, r.verification_message
    assert abs(r.objective - (-5e5)) < 1e-6 * 5e5
    assert abs(r.values["x"] - 5e5) < 1e-3
    assert abs(r.values["y"]) < 1e-9


def test_poorly_scaled_still_fails_without_scaling():
    """
    Keeps the claim in docs/limitations.md verifiable rather than merely asserted:
    the SAME instance still returns NUMERICAL_FAILURE with scaling switched off,
    which is why the equilibration layer (not a tolerance tweak) is the fix.
    """
    m = Model("t")
    m.add_variable("x", lb=0, ub=1e6)
    m.add_variable("y", lb=0, ub=1e-3)
    m.add_constraint("c1", {"x": 1e-4, "y": 1e4}, Sense.LE, 50)
    m.set_objective({"x": -1, "y": -1e-3}, ObjSense.MIN)
    r = solve_lp(m, use_scaling=False)
    assert r.status == LPStatus.NUMERICAL_FAILURE


def test_very_poorly_scaled_coefficients():
    """
    Wider spread than the case above (1e-6..1e6, i.e. 1e12) to probe how far the
    equilibration actually carries us. Hand-derived optimum: x's value density is
    1/1e-6 = 1e6 per unit capacity, y's is 1e-6/1e6 = 1e-12, so y = 0 and x binds
    at 10/1e-6 = 1e7, which is below its ub of 1e9 -> objective -1e7.
    """
    m = Model("t")
    m.add_variable("x", lb=0, ub=1e9)
    m.add_variable("y", lb=0, ub=1e-2)
    m.add_constraint("c1", {"x": 1e-6, "y": 1e6}, Sense.LE, 10)
    m.set_objective({"x": -1, "y": -1e-6}, ObjSense.MIN)
    r = solve_lp(m)
    assert r.status == LPStatus.OPTIMAL, r.verification_message
    assert r.verified_feasible, r.verification_message
    assert abs(r.objective - (-1e7)) < 1e-6 * 1e7


def test_nearly_dependent_constraints():
    # Two constraints that are almost (but not exactly) parallel/redundant.
    m = Model("t")
    m.add_variable("x", lb=0)
    m.add_variable("y", lb=0)
    m.add_constraint("c1", {"x": 1, "y": 1.0}, Sense.LE, 10)
    m.add_constraint("c2", {"x": 1, "y": 1.0001}, Sense.LE, 10.0001)
    m.set_objective({"x": -1, "y": -1}, ObjSense.MIN)
    r = solve_lp(m)
    assert r.status == LPStatus.OPTIMAL
    assert r.verified_feasible, r.verification_message
