"""Unit/integration tests for branch-and-bound MILP."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sovereign_opt.core.model import Model, Sense, ObjSense, VarType
from sovereign_opt.milp.branch_and_bound import solve_milp, MILPStatus


def test_small_knapsack_style():
    m = Model("t")
    m.add_variable("x", lb=0, ub=10, vtype=VarType.INTEGER)
    m.add_variable("y", lb=0, ub=10, vtype=VarType.INTEGER)
    m.add_constraint("c1", {"x": 6, "y": 4}, Sense.LE, 24)
    m.add_constraint("c2", {"x": 1, "y": 2}, Sense.LE, 6)
    m.set_objective({"x": -5, "y": -4}, ObjSense.MIN)  # maximize 5x+4y
    r = solve_milp(m)
    assert r.status == MILPStatus.OPTIMAL
    assert r.verified_feasible, r.verification_message
    assert abs(r.mip_gap) < 1e-9


def test_binary_knapsack():
    # classic 0/1 knapsack: items with (value, weight), capacity 10
    items = [("a", 6, 2), ("b", 10, 3), ("c", 12, 4), ("d", 5, 1), ("e", 8, 5)]
    m = Model("knap")
    for name, val, wt in items:
        m.add_variable(name, vtype=VarType.BINARY)
    m.add_constraint("cap", {n: wt for n, _, wt in items}, Sense.LE, 10)
    m.set_objective({n: -val for n, val, _ in items}, ObjSense.MIN)
    r = solve_milp(m)
    assert r.status == MILPStatus.OPTIMAL
    assert r.verified_feasible
    # brute force check
    best = 0
    n_items = len(items)
    for mask in range(1 << n_items):
        w = sum(items[i][2] for i in range(n_items) if mask & (1 << i))
        v = sum(items[i][1] for i in range(n_items) if mask & (1 << i))
        if w <= 10:
            best = max(best, v)
    assert abs(-r.objective - best) < 1e-6, f"solver={-r.objective} brute_force={best}"


def test_milp_infeasible():
    m = Model("t")
    m.add_variable("x", lb=0, ub=10, vtype=VarType.INTEGER)
    m.add_constraint("c1", {"x": 1}, Sense.LE, 1)
    m.add_constraint("c2", {"x": 1}, Sense.GE, 5)
    m.set_objective({"x": 1}, ObjSense.MIN)
    r = solve_milp(m)
    assert r.status == MILPStatus.INFEASIBLE


def test_pure_lp_via_milp_path():
    m = Model("t")
    m.add_variable("x", lb=0)
    m.add_variable("y", lb=0)
    m.add_constraint("c1", {"x": 1, "y": 1}, Sense.LE, 10)
    m.set_objective({"x": -1, "y": -1}, ObjSense.MIN)
    r = solve_milp(m)
    assert r.status == MILPStatus.OPTIMAL
    assert abs(r.objective - (-10.0)) < 1e-6


def test_integer_bounds_respected():
    m = Model("t")
    m.add_variable("x", lb=0, ub=3, vtype=VarType.INTEGER)
    m.add_constraint("c1", {"x": 1}, Sense.LE, 100)
    m.set_objective({"x": -1}, ObjSense.MIN)  # maximize x -> should hit ub=3
    r = solve_milp(m)
    assert r.status == MILPStatus.OPTIMAL
    assert abs(r.values["x"] - 3.0) < 1e-9
