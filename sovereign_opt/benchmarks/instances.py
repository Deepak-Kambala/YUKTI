"""
Small benchmark instance library.

HONESTY NOTE: This prototype's sandboxed execution environment has no
general internet access (network egress is restricted to a small list of
package registries -- see network configuration). Actual Netlib LP files
and actual MIPLIB .mps files could NOT be downloaded, so none are included
here, and nothing in this file is Netlib or MIPLIB data.

Instead, this module defines a small set of hand-built LP and MILP
instances, each with an INDEPENDENTLY KNOWN optimal objective (verified by
hand/brute-force, recorded in `known_optimal`), used to check our solver's
correctness. Some intentionally exercise degeneracy, poor scaling, and
weak LP relaxations, per the PS's request for difficult numerical cases.

If genuine Netlib/MIPLIB .mps files are supplied locally (e.g. copied into
this repo by the user outside this sandboxed environment), sovereign_opt/io
includes a basic free-format MPS reader (see io/mps_reader.py) that can
load them for the benchmark runner -- but no such files are bundled here,
and none of the numbers in docs/results.md are claimed to be Netlib/MIPLIB
results.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional
from sovereign_opt.core.model import Model, Sense, ObjSense, VarType
from sovereign_opt.industrial.refinery import generate_refinery_instance


@dataclass
class BenchmarkInstance:
    name: str
    problem_type: str  # "LP" or "MILP"
    build: Callable[[], Model]
    known_optimal: Optional[float]
    note: str = ""


def _lp1():
    m = Model("lp_textbook_2var")
    m.add_variable("x", lb=0)
    m.add_variable("y", lb=0)
    m.add_constraint("c1", {"x": 1}, Sense.LE, 4)
    m.add_constraint("c2", {"y": 2}, Sense.LE, 12)
    m.add_constraint("c3", {"x": 3, "y": 2}, Sense.LE, 18)
    m.set_objective({"x": -3, "y": -5}, ObjSense.MIN)
    return m


def _lp2_equality():
    m = Model("lp_equality_diet")
    m.add_variable("x", lb=0)
    m.add_variable("y", lb=0)
    m.add_variable("z", lb=0)
    m.add_constraint("c1", {"x": 1, "y": 1, "z": 1}, Sense.EQ, 100)
    m.add_constraint("c2", {"x": 2, "y": 1}, Sense.GE, 80)
    m.set_objective({"x": 2, "y": 3, "z": 1}, ObjSense.MIN)
    return m


def _lp3_degenerate():
    m = Model("lp_degenerate_square")
    m.add_variable("x", lb=0, ub=2)
    m.add_variable("y", lb=0, ub=2)
    m.add_constraint("c1", {"x": 1, "y": 1}, Sense.LE, 4)
    m.set_objective({"x": -1, "y": -1}, ObjSense.MIN)
    return m


def _lp4_weak_relaxation_base():
    m = Model("lp_weak_relax_base")
    m.add_variable("x", lb=0, ub=10)
    m.add_variable("y", lb=0, ub=10)
    m.add_constraint("c1", {"x": 5, "y": 4}, Sense.LE, 40)
    m.add_constraint("c2", {"x": 3, "y": 5}, Sense.LE, 37)
    m.set_objective({"x": -4, "y": -3}, ObjSense.MIN)
    return m


def _milp1_knapsack_style():
    m = Model("milp_small_ip")
    m.add_variable("x", lb=0, ub=10, vtype=VarType.INTEGER)
    m.add_variable("y", lb=0, ub=10, vtype=VarType.INTEGER)
    m.add_constraint("c1", {"x": 6, "y": 4}, Sense.LE, 24)
    m.add_constraint("c2", {"x": 1, "y": 2}, Sense.LE, 6)
    m.set_objective({"x": -5, "y": -4}, ObjSense.MIN)
    return m


def _milp2_binary_knapsack():
    items = [("a", 6, 2), ("b", 10, 3), ("c", 12, 4), ("d", 5, 1), ("e", 8, 5)]
    m = Model("milp_binary_knapsack_5item")
    for name, val, wt in items:
        m.add_variable(name, vtype=VarType.BINARY)
    m.add_constraint("cap", {n: wt for n, _, wt in items}, Sense.LE, 10)
    m.set_objective({n: -val for n, val, _ in items}, ObjSense.MIN)
    return m


def _milp3_weak_relaxation():
    # LP relaxation is far from the integer optimum by construction
    m = Model("milp_weak_relaxation")
    m.add_variable("x", lb=0, ub=1, vtype=VarType.BINARY)
    m.add_variable("y", lb=0, ub=1, vtype=VarType.BINARY)
    m.add_variable("z", lb=0, ub=1, vtype=VarType.BINARY)
    m.add_constraint("c1", {"x": 1, "y": 1, "z": 1}, Sense.LE, 1)  # at most one
    m.set_objective({"x": -4, "y": -5, "z": -6}, ObjSense.MIN)  # pick best single item -> z=1, obj=-6
    return m


def _milp4_infeasible():
    m = Model("milp_infeasible")
    m.add_variable("x", lb=0, ub=10, vtype=VarType.INTEGER)
    m.add_constraint("c1", {"x": 1}, Sense.LE, 1)
    m.add_constraint("c2", {"x": 1}, Sense.GE, 5)
    m.set_objective({"x": 1}, ObjSense.MIN)
    return m


def _lp_ill_conditioned_1e8():
    """
    Magnitude spread 1e8 in a single row. Hand-derived optimum: x yields
    1/1e-4 = 1e4 objective units per unit of constraint capacity, y yields
    1e-3/1e4 = 1e-7, so y stays 0 and x binds the row at 50/1e-4 = 5e5
    (below its own ub of 1e6) -> objective -5e5.
    This instance returns NUMERICAL_FAILURE with equilibration disabled.
    """
    m = Model("lp_ill_conditioned_1e8")
    m.add_variable("x", lb=0, ub=1e6)
    m.add_variable("y", lb=0, ub=1e-3)
    m.add_constraint("c1", {"x": 1e-4, "y": 1e4}, Sense.LE, 50)
    m.set_objective({"x": -1, "y": -1e-3}, ObjSense.MIN)
    return m


def _lp_ill_conditioned_1e12():
    """
    Magnitude spread 1e12. Same structure, wider range: x's value density is
    1/1e-6 = 1e6 per unit capacity vs y's 1e-6/1e6 = 1e-12, so y = 0 and x
    binds at 10/1e-6 = 1e7 (below its ub of 1e9) -> objective -1e7.
    """
    m = Model("lp_ill_conditioned_1e12")
    m.add_variable("x", lb=0, ub=1e9)
    m.add_variable("y", lb=0, ub=1e-2)
    m.add_constraint("c1", {"x": 1e-6, "y": 1e6}, Sense.LE, 10)
    m.set_objective({"x": -1, "y": -1e-6}, ObjSense.MIN)
    return m


def _lp_mixed_units_ill_conditioned():
    """
    Multi-row, multi-column ill-conditioned LP imitating a units mismatch
    (throughput in millions of units, a trace-quality term in ppm). Magnitude
    spread 1e9 across rows.

        min  -(3a + 4b + 1e5 c)
        s.t. 1e-5 a + 2e-5 b <= 1        (a + 2b <= 1e5)
             1e4 c           <= 50       (c <= 5e-3)
             a in [0,1e5], b in [0,1e5], c in [0,1e-2]

    Hand-derived optimum: per unit of row-1 capacity, a returns 3/1e-5 = 3e5
    and b returns 4/2e-5 = 2e5, so all capacity goes to a: a = 1e5 (exactly
    exhausting row 1 and hitting a's own ub), b = 0. c is unconstrained by
    those rows and binds row 2 at c = 5e-3 (below its ub 1e-2), contributing
    1e5 * 5e-3 = 500. Objective = -(3*1e5 + 500) = -300500.
    """
    m = Model("lp_mixed_units_ill_conditioned")
    m.add_variable("a", lb=0, ub=1e5)
    m.add_variable("b", lb=0, ub=1e5)
    m.add_variable("c", lb=0, ub=1e-2)
    m.add_constraint("capacity", {"a": 1e-5, "b": 2e-5}, Sense.LE, 1)
    m.add_constraint("trace_quality", {"c": 1e4}, Sense.LE, 50)
    m.set_objective({"a": -3, "b": -4, "c": -1e5}, ObjSense.MIN)
    return m


def get_instances():
    instances = [
        BenchmarkInstance("lp_textbook_2var", "LP", _lp1, -36.0,
                           "Textbook 2-variable LP, hand-verified optimum."),
        BenchmarkInstance("lp_equality_diet", "LP", _lp2_equality, 140.0,
                           "Equality-constrained LP; hand-derived optimum x=40,y=0,z=60 -> obj=140, "
                           "confirmed to match the solver's independently-verified result."),
        BenchmarkInstance("lp_degenerate_square", "LP", _lp3_degenerate, -4.0,
                           "Degenerate vertex (multiple bounding constraints active simultaneously)."),
        BenchmarkInstance("lp_weak_relax_base", "LP", _lp4_weak_relaxation_base, None,
                           "Base LP used (with added integrality) as a weak-relaxation MILP stress case."),
        BenchmarkInstance("lp_ill_conditioned_1e8", "LP", _lp_ill_conditioned_1e8, -5e5,
                           "Ill-conditioned LP, coefficient magnitude spread 1e8. Hand-derived optimum "
                           "-500000. Returns NUMERICAL_FAILURE without the equilibration layer "
                           "(linalg/scaling.py); solved with it."),
        BenchmarkInstance("lp_ill_conditioned_1e12", "LP", _lp_ill_conditioned_1e12, -1e7,
                           "Ill-conditioned LP, coefficient magnitude spread 1e12. Hand-derived optimum "
                           "-10000000."),
        BenchmarkInstance("lp_mixed_units_ill_conditioned", "LP", _lp_mixed_units_ill_conditioned, -300500.0,
                           "Multi-row ill-conditioned LP imitating a units mismatch (spread 1e9). "
                           "Hand-derived optimum -300500."),
        BenchmarkInstance("milp_small_ip", "MILP", _milp1_knapsack_style, None,
                           "Small general-integer MILP; optimum determined by solver + independent verification."),
        BenchmarkInstance("milp_binary_knapsack_5item", "MILP", _milp2_binary_knapsack, -33.0,
                           "5-item 0/1 knapsack, capacity 10; model MINIMIZES -value, so optimal objective "
                           "is -33 (items a+b+c+d, weight 10, true max value 33), cross-checked by brute "
                           "force over all 32 subsets in tests/test_milp.py."),
        BenchmarkInstance("milp_weak_relaxation", "MILP", _milp3_weak_relaxation, -6.0,
                           "3-binary 'pick at most one' MILP; LP relaxation allows fractional mixing, "
                           "true optimum is single best item (z=1) -> -6."),
        BenchmarkInstance("milp_infeasible", "MILP", _milp4_infeasible, None,
                           "Deliberately infeasible MILP (x<=1 and x>=5 simultaneously)."),
    ]
    for size, params in [("small", dict(n_crudes=3, n_products=2)),
                          ("medium", dict(n_crudes=6, n_products=4)),
                          ("large", dict(n_crudes=12, n_products=8))]:
        instances.append(BenchmarkInstance(
            f"refinery_lp_{size}", "LP",
            (lambda p=params: generate_refinery_instance(**p, seed=42)),
            None, f"Synthetic refinery blending LP, {size} instance size. NOT real refinery data."))
    instances.append(BenchmarkInstance(
        "refinery_milp_small_batches", "MILP",
        (lambda: generate_refinery_instance(n_crudes=3, n_products=2, seed=42,
                                             integer_batches=True, batch_unit=50)),
        None, "Synthetic refinery blending MILP with discretized integer batch volumes. NOT real refinery data."))
    return instances
