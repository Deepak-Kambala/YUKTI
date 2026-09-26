"""
Branch-and-bound MILP solver built entirely on our own LP solver
(sovereign_opt.lp.simplex / orchestrator). No external MILP/LP solver is
used anywhere in this module.

Implements:
  - LP relaxation at each node (with presolve)
  - integer feasibility checking
  - simple most-fractional variable branching (a defensible, simple default)
  - depth-first node queue (a plain stack) with best-first-ish pruning via
    the incumbent bound
  - incumbent tracking, lower/upper bound (best bound) tracking
  - MIP gap calculation
  - node/time limits as termination criteria

Explicitly NOT implemented (see docs/limitations.md): pseudocost branching,
primal heuristics, cutting planes, warm-starting between nodes (each node's
LP relaxation is solved from scratch).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import time

from sovereign_opt.core.model import Model, VarType, ObjSense
from sovereign_opt.lp.orchestrator import solve_lp_with_presolve
from sovereign_opt.linalg.scaling import DEFAULT_SCALING_THRESHOLD
from sovereign_opt.lp.simplex import LPStatus


class MILPStatus(Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE_NOT_PROVEN_OPTIMAL"
    INFEASIBLE = "INFEASIBLE"
    NODE_LIMIT = "NODE_LIMIT"
    TIME_LIMIT = "TIME_LIMIT"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"


@dataclass
class MILPResult:
    status: MILPStatus
    objective: Optional[float] = None
    best_bound: Optional[float] = None
    values: Dict[str, float] = field(default_factory=dict)
    nodes_explored: int = 0
    mip_gap: Optional[float] = None
    runtime_sec: float = 0.0
    lp_relaxation_objective: Optional[float] = None
    verified_feasible: bool = False
    verification_message: str = ""
    # Nodes whose LP relaxation did not solve (not INFEASIBLE, which is a sound
    # prune). Non-zero means part of the tree was never explored, so OPTIMAL is
    # not reported -- see the pruning branch in solve_milp().
    abandoned_nodes: int = 0


def _is_integer_feasible(model: Model, values: Dict[str, float], tol: float) -> Tuple[bool, Optional[str], float]:
    """Returns (is_feasible, most_fractional_var_or_None, max_fractionality)."""
    worst_var = None
    worst_frac = -1.0
    for vn, v in model.variables.items():
        if not v.is_integer():
            continue
        val = values[vn]
        frac = abs(val - round(val))
        if frac > tol and frac > worst_frac:
            worst_frac = frac
            worst_var = vn
    return worst_var is None, worst_var, max(worst_frac, 0.0)


def solve_milp(model: Model, tol: float = 1e-6, node_limit: int = 20000,
               time_limit_sec: float = 60.0, gap_tol: float = 1e-6,
               use_scaling: bool = True,
               scaling_threshold: float = DEFAULT_SCALING_THRESHOLD) -> MILPResult:
    t0 = time.time()

    root = solve_lp_with_presolve(model, use_presolve=True, use_scaling=use_scaling,
                                  scaling_threshold=scaling_threshold)
    if root.status == LPStatus.INFEASIBLE:
        return MILPResult(status=MILPStatus.INFEASIBLE, nodes_explored=0, runtime_sec=time.time() - t0)
    if root.status != LPStatus.OPTIMAL:
        return MILPResult(status=MILPStatus.NUMERICAL_FAILURE, nodes_explored=0, runtime_sec=time.time() - t0)

    if not model.is_milp():
        # pure LP disguised as an MILP call
        ok, msg = root.verified_feasible, root.verification_message
        return MILPResult(status=MILPStatus.OPTIMAL if ok else MILPStatus.NUMERICAL_FAILURE,
                           objective=root.objective, best_bound=root.objective,
                           values=root.values, nodes_explored=1, mip_gap=0.0 if ok else None,
                           runtime_sec=time.time() - t0, lp_relaxation_objective=root.objective,
                           verified_feasible=ok, verification_message=msg)

    lp_relax_obj = root.objective

    # minimize internally regardless of model.obj_sense (Model stores cost
    # coefficients already oriented so that solve_lp always minimizes;
    # ObjSense.MAX problems must have been given negated coefficients by the
    # caller, consistent with sovereign_opt.core.model.Model.set_objective's
    # documented convention). We therefore always treat this as a
    # minimization branch-and-bound.
    incumbent_obj = None
    incumbent_values = None
    best_bound = lp_relax_obj

    # stack of (lb_overrides, ub_overrides) dictionaries applied on top of model
    stack: List[Tuple[Dict[str, float], Dict[str, float]]] = [({}, {})]
    nodes_explored = 0
    abandoned_nodes = 0   # nodes whose LP relaxation did not solve (see below)

    while stack:
        nodes_explored += 1
        if nodes_explored > node_limit:
            status = MILPStatus.NODE_LIMIT
            return _finish(model, status, incumbent_obj, incumbent_values, best_bound,
                            nodes_explored, t0, lp_relax_obj, gap_tol)
        if time.time() - t0 > time_limit_sec:
            status = MILPStatus.TIME_LIMIT
            return _finish(model, status, incumbent_obj, incumbent_values, best_bound,
                            nodes_explored, t0, lp_relax_obj, gap_tol)

        lb_over, ub_over = stack.pop()
        node_model = _apply_bounds(model, lb_over, ub_over)

        rep = solve_lp_with_presolve(node_model, use_presolve=True, use_scaling=use_scaling,
                                     scaling_threshold=scaling_threshold)
        if rep.status == LPStatus.INFEASIBLE:
            continue  # proven empty subtree: a sound prune
        if rep.status != LPStatus.OPTIMAL:
            # UNBOUNDED / ITERATION_LIMIT / NUMERICAL_FAILURE: this node's
            # relaxation did not solve, so the subtree was neither explored nor
            # proven empty. Dropping it is NOT a sound prune -- record it, so
            # the final status cannot claim proven optimality (or proven
            # infeasibility) over a tree we did not actually finish.
            abandoned_nodes += 1
            continue

        node_obj = rep.objective

        # bound pruning: if this relaxation is already worse (or equal,
        # within tol) than the incumbent, prune (minimization)
        if incumbent_obj is not None and node_obj >= incumbent_obj - gap_tol:
            continue

        feasible, frac_var, frac = _is_integer_feasible(model, rep.values, tol)
        if feasible:
            incumbent_obj = node_obj
            incumbent_values = rep.values
            continue

        # branch on most-fractional integer variable
        val = rep.values[frac_var]
        floor_v, ceil_v = float(int(val // 1)), float(int(val // 1) + 1)

        lb1, ub1 = dict(lb_over), dict(ub_over)
        ub1[frac_var] = min(ub1.get(frac_var, model.variables[frac_var].ub), floor_v)

        lb2, ub2 = dict(lb_over), dict(ub_over)
        lb2[frac_var] = max(lb2.get(frac_var, model.variables[frac_var].lb), ceil_v)

        stack.append((lb1, ub1))
        stack.append((lb2, ub2))

        # recompute best_bound as the min LP relaxation among remaining open
        # nodes is expensive to track exactly with a plain stack; we instead
        # report best_bound = lp_relax_obj (root bound) until the search
        # completes, at which point (if stack empties) best_bound == incumbent.

    if abandoned_nodes:
        # At least one subtree was left unexplored because its LP relaxation
        # did not solve. Neither optimality nor infeasibility is proven, so
        # report only what was actually established, with the root relaxation
        # as the one bound still known to be valid.
        status = (MILPStatus.FEASIBLE if incumbent_obj is not None
                  else MILPStatus.NUMERICAL_FAILURE)
        best_bound = lp_relax_obj
    else:
        status = MILPStatus.OPTIMAL if incumbent_obj is not None else MILPStatus.INFEASIBLE
        best_bound = incumbent_obj if incumbent_obj is not None else best_bound
    return _finish(model, status, incumbent_obj, incumbent_values, best_bound,
                    nodes_explored, t0, lp_relax_obj, gap_tol,
                    abandoned_nodes=abandoned_nodes)


def _finish(model, status, incumbent_obj, incumbent_values, best_bound, nodes_explored,
            t0, lp_relax_obj, gap_tol, abandoned_nodes=0):
    runtime = time.time() - t0
    if incumbent_obj is None:
        return MILPResult(status=status, nodes_explored=nodes_explored, runtime_sec=runtime,
                           lp_relaxation_objective=lp_relax_obj,
                           abandoned_nodes=abandoned_nodes)

    if status == MILPStatus.OPTIMAL:
        gap = 0.0
    else:
        denom = max(1e-10, abs(incumbent_obj))
        gap = abs(incumbent_obj - best_bound) / denom
        status = MILPStatus.FEASIBLE if status not in (MILPStatus.NODE_LIMIT, MILPStatus.TIME_LIMIT) else status

    ok, msg = _verify_milp(model, incumbent_values, incumbent_obj)
    if not ok:
        # Same fail-loud rule as the LP layer: an incumbent that fails the
        # independent integrality/feasibility/objective re-check is never
        # reported as OPTIMAL or FEASIBLE.
        status = MILPStatus.NUMERICAL_FAILURE
        msg = f"REJECTED (failed independent verification): {msg}"
    return MILPResult(status=status, objective=incumbent_obj, best_bound=best_bound,
                       values=incumbent_values, nodes_explored=nodes_explored,
                       mip_gap=gap, runtime_sec=runtime, lp_relaxation_objective=lp_relax_obj,
                       verified_feasible=ok, verification_message=msg,
                       abandoned_nodes=abandoned_nodes)


def _verify_milp(model: Model, values: Dict[str, float], objective: float, tol: float = 1e-5):
    if values is None:
        return False, "No incumbent to verify"
    for vn, v in model.variables.items():
        val = values[vn]
        if val < v.lb - tol or val > v.ub + tol:
            return False, f"Variable {vn}={val} violates bounds [{v.lb},{v.ub}]"
        if v.is_integer() and abs(val - round(val)) > 1e-5:
            return False, f"Variable {vn}={val} not integral"
    from sovereign_opt.core.model import Sense
    for c in model.constraints:
        lhs = sum(coeff * values[vn] for vn, coeff in c.coeffs.items())
        if c.sense == Sense.LE and lhs > c.rhs + tol:
            return False, f"Constraint {c.name} violated: {lhs} > {c.rhs}"
        if c.sense == Sense.GE and lhs < c.rhs - tol:
            return False, f"Constraint {c.name} violated: {lhs} < {c.rhs}"
        if c.sense == Sense.EQ and abs(lhs - c.rhs) > tol:
            return False, f"Constraint {c.name} violated: {lhs} != {c.rhs}"
    recompute = sum(model.variables[vn].obj_coeff * val for vn, val in values.items())
    if abs(recompute - objective) > max(tol, 1e-6 * abs(objective)):
        return False, f"Objective mismatch: reported {objective}, recomputed {recompute}"
    return True, "Integer feasibility, constraints and objective independently verified"


def _apply_bounds(model: Model, lb_over: Dict[str, float], ub_over: Dict[str, float]) -> Model:
    m2 = model.copy()
    for vn, lb in lb_over.items():
        m2.variables[vn].lb = lb
    for vn, ub in ub_over.items():
        m2.variables[vn].ub = ub
    return m2
