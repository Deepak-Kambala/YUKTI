"""MPS reader/writer round-trip tests (against our own generated instances only --
see docs/limitations.md: this reader is NOT validated against real external
Netlib/MIPLIB .mps files, since this environment has no general internet access)."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sovereign_opt.core.model import Model, Sense, ObjSense, VarType
from sovereign_opt.io.mps_format import write_mps, read_mps
from sovereign_opt.lp.simplex import solve_lp, LPStatus
from sovereign_opt.milp.branch_and_bound import solve_milp, MILPStatus


def test_lp_roundtrip_objective_matches():
    m = Model("t")
    m.add_variable("x", lb=0, ub=4)
    m.add_variable("y", lb=0)
    m.add_constraint("c1", {"y": 2}, Sense.LE, 12)
    m.add_constraint("c2", {"x": 3, "y": 2}, Sense.LE, 18)
    m.set_objective({"x": -3, "y": -5}, ObjSense.MIN)

    with tempfile.NamedTemporaryFile(suffix=".mps", delete=False) as f:
        path = f.name
    write_mps(m, path)
    m2 = read_mps(path)
    os.unlink(path)

    r1 = solve_lp(m)
    r2 = solve_lp(m2)
    assert r1.status == r2.status == LPStatus.OPTIMAL
    assert abs(r1.objective - r2.objective) < 1e-6


def test_milp_roundtrip_with_integer_markers():
    m = Model("t")
    m.add_variable("x", lb=0, ub=10, vtype=VarType.INTEGER)
    m.add_variable("y", lb=0, ub=1, vtype=VarType.BINARY)
    m.add_constraint("c1", {"x": 6, "y": 4}, Sense.LE, 24)
    m.add_constraint("c2", {"x": 1, "y": 2}, Sense.LE, 6)
    m.set_objective({"x": -5, "y": -4}, ObjSense.MIN)

    with tempfile.NamedTemporaryFile(suffix=".mps", delete=False) as f:
        path = f.name
    write_mps(m, path)
    m2 = read_mps(path)
    os.unlink(path)

    assert m2.variables["x"].is_integer()

    r1 = solve_milp(m)
    r2 = solve_milp(m2)
    assert r1.status == r2.status == MILPStatus.OPTIMAL
    assert abs(r1.objective - r2.objective) < 1e-6
