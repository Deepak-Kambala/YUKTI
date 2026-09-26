"""Unit tests for presolve reversibility."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sovereign_opt.core.model import Model, Sense, ObjSense
from sovereign_opt.presolve.presolve import presolve, postsolve_values
from sovereign_opt.lp.orchestrator import solve_lp_with_presolve
from sovereign_opt.lp.simplex import solve_lp, LPStatus


def test_fixed_variable_folds_correctly():
    m = Model("t")
    m.add_variable("x", lb=0, ub=10)
    m.add_variable("y", lb=2, ub=2)
    m.add_constraint("c1", {"x": 1, "y": 1}, Sense.LE, 15)
    m.set_objective({"x": 1, "y": 1}, ObjSense.MIN)
    rep = solve_lp_with_presolve(m)
    assert rep.status == LPStatus.OPTIMAL
    assert abs(rep.objective - 2.0) < 1e-6  # x->0, y fixed at 2
    assert rep.verified_feasible


def test_presolve_matches_no_presolve_objective():
    m = Model("t")
    m.add_variable("x", lb=0, ub=10)
    m.add_variable("y", lb=0, ub=10)
    m.add_variable("z", lb=3, ub=3)
    m.add_constraint("c1", {"x": 2, "y": 1, "z": 1}, Sense.LE, 20)
    m.add_constraint("c2", {"x": 1}, Sense.GE, 2)
    m.set_objective({"x": 3, "y": 1, "z": 5}, ObjSense.MIN)

    rep_pre = solve_lp_with_presolve(m, use_presolve=True)
    rep_nopre = solve_lp_with_presolve(m, use_presolve=False)
    assert rep_pre.status == rep_nopre.status == LPStatus.OPTIMAL
    assert abs(rep_pre.objective - rep_nopre.objective) < 1e-6


def test_infeasible_detected_in_presolve():
    m = Model("t")
    m.add_variable("x", lb=5, ub=3)  # lb > ub directly -> will be caught by fix check inconsistency
    m.set_objective({"x": 1}, ObjSense.MIN)
    rep = solve_lp_with_presolve(m)
    assert rep.status == LPStatus.INFEASIBLE


def test_singleton_row_tightens_bound():
    m = Model("t")
    m.add_variable("x", lb=0, ub=100)
    m.add_constraint("c1", {"x": 2}, Sense.LE, 10)  # x <= 5
    m.set_objective({"x": -1}, ObjSense.MIN)  # maximize x -> should get 5
    rep = solve_lp_with_presolve(m)
    assert rep.status == LPStatus.OPTIMAL
    assert abs(rep.values["x"] - 5.0) < 1e-6
