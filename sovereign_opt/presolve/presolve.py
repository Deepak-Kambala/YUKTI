"""
Basic, reversible presolve.

Implements (documented honestly -- see docs/limitations.md for what is
NOT implemented, e.g. no dual reductions, no coefficient tightening on
inequalities beyond simple bound propagation):

  1. Fixed variables (lb == ub)              -> substitute out
  2. Empty rows                              -> drop (check feasibility)
  3. Empty columns (improving bound finite) -> fix at best bound for obj
     (a column whose improving bound is INFINITE is deliberately left in
     place, so the simplex can report UNBOUNDED rather than presolve
     inventing a finite value -- see the comment at that reduction)
  4. Singleton rows (single nonzero coeff)   -> convert to a variable bound
  5. Simple bound tightening from singleton rows

Every reduction records enough information in a PresolveLog to reverse
the mapping and recover original-space variable values after solving the
reduced problem.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from sovereign_opt.core.model import Model, Sense, ObjSense, Variable, INF


@dataclass
class PresolveAction:
    kind: str
    data: dict


@dataclass
class PresolveLog:
    actions: List[PresolveAction] = field(default_factory=list)
    original_var_names: List[str] = field(default_factory=list)
    infeasible: bool = False
    infeasible_reason: str = ""

    def record(self, kind: str, **data):
        self.actions.append(PresolveAction(kind, data))


def presolve(model: Model, tol: float = 1e-9) -> Tuple[Model, PresolveLog]:
    """Returns (reduced_model, log). Does not mutate the input model."""
    m = model.copy()
    log = PresolveLog(original_var_names=list(model.var_order))
    changed = True
    fixed_values: Dict[str, float] = {}

    # 0. directly infeasible bounds (lb > ub)
    for vn, v in m.variables.items():
        if v.lb > v.ub + tol:
            log.infeasible = True
            log.infeasible_reason = f"Variable '{vn}' has lb={v.lb} > ub={v.ub}"
            return m, log

    while changed:
        changed = False

        # 1. fixed variables (lb == ub, strictly -- not lb > ub, handled above)
        for vn in list(m.variables.keys()):
            v = m.variables[vn]
            if abs(v.ub - v.lb) <= tol and vn not in fixed_values:
                fixed_values[vn] = v.lb
                log.record("fix_variable", var=vn, value=v.lb)
                changed = True

        if fixed_values:
            m = _substitute_fixed(m, fixed_values)
            fixed_values = {}

        # 2. empty rows
        keep_constraints = []
        for c in m.constraints:
            if len(c.coeffs) == 0:
                ok = (c.sense == Sense.LE and 0 <= c.rhs + tol) or \
                     (c.sense == Sense.GE and 0 >= c.rhs - tol) or \
                     (c.sense == Sense.EQ and abs(c.rhs) <= tol)
                log.record("drop_empty_row", constraint=c.name, feasible=ok)
                if not ok:
                    log.infeasible = True
                    log.infeasible_reason = f"Empty row '{c.name}' infeasible: 0 {c.sense.value} {c.rhs}"
                changed = True
                continue
            keep_constraints.append(c)
        if len(keep_constraints) != len(m.constraints):
            m.constraints = keep_constraints

        if log.infeasible:
            return m, log

        # 3. singleton rows -> bound tightening
        new_constraints = []
        for c in m.constraints:
            if len(c.coeffs) == 1:
                (vn, coeff), = c.coeffs.items()
                v = m.variables[vn]
                if coeff == 0:
                    continue
                bound_val = c.rhs / coeff
                if c.sense == Sense.EQ:
                    lo = hi = bound_val
                elif (c.sense == Sense.LE and coeff > 0) or (c.sense == Sense.GE and coeff < 0):
                    lo, hi = -INF, bound_val
                else:
                    lo, hi = bound_val, INF
                new_lb = max(v.lb, lo)
                new_ub = min(v.ub, hi)
                if new_lb > new_ub + tol:
                    log.infeasible = True
                    log.infeasible_reason = f"Singleton row '{c.name}' makes {vn} infeasible: [{new_lb},{new_ub}]"
                    return m, log
                if new_lb != v.lb or new_ub != v.ub:
                    log.record("tighten_bound", var=vn, old_lb=v.lb, old_ub=v.ub, new_lb=new_lb, new_ub=new_ub,
                                from_constraint=c.name)
                    v.lb, v.ub = new_lb, new_ub
                    changed = True
                log.record("drop_singleton_row", constraint=c.name)
                continue
            new_constraints.append(c)
        if len(new_constraints) != len(m.constraints):
            m.constraints = new_constraints
            changed = True

    # 4. empty columns (var appears in no remaining constraint) -> fix at
    #    the bound that is best for the (minimization) objective
    used_vars = set()
    for c in m.constraints:
        used_vars.update(c.coeffs.keys())
    fixed_values = {}
    for vn, v in m.variables.items():
        if vn not in used_vars:
            # Minimization convention (see Model.set_objective): the improving
            # direction is the lower bound for a positive cost and the upper
            # bound for a negative cost.
            if v.obj_coeff > 0:
                val = v.lb
            elif v.obj_coeff < 0:
                val = v.ub
            else:
                val = v.lb if v.lb > -INF else v.ub  # zero cost: any bound will do
            if val <= -INF or val >= INF:
                # The bound this column wants is infinite, so the column alone
                # makes the LP unbounded (or, with lb=-inf, free -- which this
                # prototype does not support). Presolve must NOT invent a finite
                # value here: doing so silently turns an UNBOUNDED model into a
                # wrong OPTIMAL, and the independent verifier cannot catch it
                # because the invented point is feasible and its objective is
                # self-consistent. Leave the column in the reduced model and let
                # the simplex's own unboundedness / free-variable test decide.
                log.record("keep_unbounded_empty_column", var=vn, obj_coeff=v.obj_coeff)
                continue
            fixed_values[vn] = val
            log.record("fix_empty_column", var=vn, value=val)
    if fixed_values:
        m = _substitute_fixed(m, fixed_values)

    return m, log


def _substitute_fixed(model: Model, fixed_values: Dict[str, float]) -> Model:
    """Remove fixed variables from the model, folding their contribution
    into constraint RHS and recording them so postsolve can restore them."""
    m2 = Model(name=model.name, obj_sense=model.obj_sense)
    for vn in model.var_order:
        if vn in fixed_values:
            continue
        v = model.variables[vn]
        m2.add_variable(vn, lb=v.lb, ub=v.ub, vtype=v.vtype, obj=v.obj_coeff)
    for c in model.constraints:
        new_coeffs = {}
        new_rhs = c.rhs
        for vn, coeff in c.coeffs.items():
            if vn in fixed_values:
                new_rhs -= coeff * fixed_values[vn]
            else:
                new_coeffs[vn] = coeff
        m2.add_constraint(c.name, new_coeffs, c.sense, new_rhs)
    return m2


def postsolve_values(original_model: Model, log: PresolveLog, reduced_values: Dict[str, float]) -> Dict[str, float]:
    """Map a solution of the reduced problem back to the original variable set."""
    values = dict(reduced_values)
    # Replay fix actions in reverse order so later fixes (which may depend on
    # earlier substitutions being already folded into rhs) are restored correctly.
    for action in reversed(log.actions):
        if action.kind in ("fix_variable", "fix_empty_column"):
            values[action.data["var"]] = action.data["value"]
    # ensure every original variable has a value
    for vn in log.original_var_names:
        if vn not in values:
            values[vn] = original_model.variables[vn].lb
    return values
