"""
Genuine two-phase revised simplex method, implemented from scratch.

Design (documented honestly, see docs/limitations.md):
- Variables are shifted so lower bound = 0 (y = x - lb). Free (lb = -inf)
  variables are NOT supported in this prototype.
- Finite upper bounds are handled as explicit "<=" rows (y_j <= ub_j - lb_j)
  rather than native bounded-variable simplex. Simpler, fully correct,
  less memory/iteration-efficient.
- Every constraint row gets an artificial variable (sign chosen so the
  all-artificial basis is feasible at y=0) to make phase 1 uniform and
  robust rather than trying to special-case which rows need one.
- The basis matrix B is rebuilt and re-solved from scratch every iteration
  via sovereign_opt.linalg.gauss (our own Gaussian elimination) -- this is
  "textbook" revised simplex without LU-update / product-form-of-inverse
  acceleration. That is a real, measured performance limitation, not
  hidden: complexity is O(m^3) per iteration.
- Bland's rule (smallest index) is used for both entering-variable and
  leaving-variable (ratio-test tie-break) selection, which guarantees no
  cycling, at some cost in iteration count versus Dantzig's rule.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import numpy as np
import time

from sovereign_opt.core.model import Model, Sense, ObjSense, INF
from sovereign_opt.linalg.gauss import gauss_solve, gauss_solve_transpose, SingularBasisError
from sovereign_opt.linalg.scaling import (auto_scaling, identity_scaling, cost_scale,
                                          DEFAULT_SCALING_THRESHOLD)


class LPStatus(Enum):
    OPTIMAL = "OPTIMAL"
    INFEASIBLE = "INFEASIBLE"
    UNBOUNDED = "UNBOUNDED"
    ITERATION_LIMIT = "ITERATION_LIMIT"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"


@dataclass
class LPResult:
    status: LPStatus
    objective: float = 0.0
    values: Dict[str, float] = field(default_factory=dict)
    iterations: int = 0
    phase1_iterations: int = 0
    phase2_iterations: int = 0
    runtime_sec: float = 0.0
    verified_feasible: bool = False
    verification_message: str = ""
    scaling_summary: str = ""


class _StdForm:
    """Internal standard-form representation built from a Model."""

    def __init__(self, model: Model, tol: float, use_scaling: bool = True,
                 scaling_threshold: float = DEFAULT_SCALING_THRESHOLD):
        self.model = model
        self.tol = tol
        self.var_names = list(model.var_order)
        n_orig = len(self.var_names)

        # bound checks (document unsupported case loudly rather than silently
        # producing a wrong answer)
        for vn in self.var_names:
            v = model.variables[vn]
            if v.lb == -INF:
                raise NotImplementedError(
                    f"Variable '{vn}' has lb=-inf (free variable). "
                    "Free variables are not supported by this prototype simplex; "
                    "supply a finite lower bound."
                )

        self.lb = np.array([model.variables[vn].lb for vn in self.var_names], dtype=np.float64)
        self.obj = np.array([model.variables[vn].obj_coeff for vn in self.var_names], dtype=np.float64)
        self.obj_sense = model.obj_sense
        self.obj_offset = float(np.dot(self.obj, self.lb))  # c.x = c.y + offset

        # Build row list for the ORIGINAL constraints only (rhs shifted by lb).
        # Upper-bound rows are generated AFTER scaling, from the scaled bounds,
        # so that they keep a unit coefficient.
        cons_rows = []  # each: (coeffs: dict[col_idx]->val, sense, rhs)
        idx_of = {vn: j for j, vn in enumerate(self.var_names)}
        for c in model.constraints:
            coeffs = {}
            rhs = c.rhs
            for vn, coeff in c.coeffs.items():
                j = idx_of[vn]
                coeffs[j] = coeffs.get(j, 0.0) + coeff
                rhs -= coeff * self.lb[j]
            cons_rows.append((coeffs, c.sense, rhs))

        # ---- Automatic equilibration (see linalg/scaling.py) ----
        # y_j = d_j * y_hat_j  (column scaling), row i scaled by r_i > 0.
        # Both are exactly reversed below when the solution is recovered.
        # Applied only to models whose magnitude spread exceeds the threshold,
        # so well-scaled models keep their previously validated numerical path.
        if use_scaling:
            self.scaling = auto_scaling([r[0] for r in cons_rows], n_orig,
                                        threshold=scaling_threshold)
        else:
            self.scaling = identity_scaling(len(cons_rows), n_orig)
        rscale, cscale = self.scaling.row, self.scaling.col
        self.col_scale = cscale

        rows = []
        for i, (coeffs, sense, rhs) in enumerate(cons_rows):
            rows.append(({j: v * cscale[j] * rscale[i] for j, v in coeffs.items()},
                          sense, rhs * rscale[i]))

        # explicit upper-bound rows in scaled space: y_hat_j <= (ub_j - lb_j) / d_j
        for j, vn in enumerate(self.var_names):
            ub = model.variables[vn].ub
            if ub < INF:
                rows.append(({j: 1.0}, Sense.LE, (ub - self.lb[j]) / cscale[j]))

        # Objective in scaled column space, then one uniform cost factor so the
        # absolute reduced-cost tolerance is meaningful. Both undone on report.
        # Tied to `applied` so an untouched model's reduced costs are untouched too.
        scaled_obj = self.obj * cscale
        self.cost_scale = cost_scale(scaled_obj) if self.scaling.applied else 1.0
        self.obj_scaled = scaled_obj * self.cost_scale

        self.n_rows = len(rows)
        m = self.n_rows
        # columns: n_orig structural + one slack/surplus per row (may be 0 col for '=') + one artificial per row
        self.slack_col = [-1] * m
        self.artificial_col = [-1] * m
        col = n_orig
        for i, (_, sense, _) in enumerate(rows):
            if sense != Sense.EQ:
                self.slack_col[i] = col
                col += 1
        for i in range(m):
            self.artificial_col[i] = col
            col += 1
        self.n_cols = col

        A = np.zeros((m, self.n_cols), dtype=np.float64)
        b = np.zeros(m, dtype=np.float64)
        for i, (coeffs, sense, rhs) in enumerate(rows):
            for j, v in coeffs.items():
                A[i, j] = v
            sign = 1.0 if rhs >= 0 else -1.0
            if sense == Sense.LE:
                A[i, self.slack_col[i]] = 1.0
            elif sense == Sense.GE:
                A[i, self.slack_col[i]] = -1.0
            A[i, self.artificial_col[i]] = sign
            b[i] = rhs
        self.A = A
        self.b = b
        self.n_orig = n_orig
        self.basis = list(self.artificial_col)  # initial feasible basis: all artificials


def _run_simplex_phase(std: _StdForm, cost: np.ndarray, basis: List[int],
                        allowed_cols: Optional[np.ndarray], max_iter: int, tol: float):
    """Runs primal simplex (Bland's rule) given a starting feasible basis.
    Returns (status, basis, x_full, iterations)."""
    A = std.A
    b = std.b
    m, n = A.shape
    it = 0
    while it < max_iter:
        it += 1
        B = A[:, basis]
        try:
            xB = gauss_solve(B, b, tol=tol)
        except SingularBasisError as e:
            return LPStatus.NUMERICAL_FAILURE, basis, None, it
        c_B = cost[basis]
        try:
            y = gauss_solve_transpose(B, c_B, tol=tol)
        except SingularBasisError:
            return LPStatus.NUMERICAL_FAILURE, basis, None, it

        # reduced costs for nonbasic, eligible columns, Bland's rule (smallest index)
        basis_set = set(basis)
        entering = -1
        for j in range(n):
            if j in basis_set:
                continue
            if allowed_cols is not None and not allowed_cols[j]:
                continue
            rc = cost[j] - float(np.dot(y, A[:, j]))
            if rc < -tol:
                entering = j
                break  # Bland's rule: first eligible index

        if entering == -1:
            x_full = np.zeros(n)
            for i, bi in enumerate(basis):
                x_full[bi] = xB[i]
            return LPStatus.OPTIMAL, basis, x_full, it

        try:
            d = gauss_solve(B, A[:, entering], tol=tol)
        except SingularBasisError:
            return LPStatus.NUMERICAL_FAILURE, basis, None, it

        leaving_row = -1
        best_ratio = None
        best_basis_idx = None
        for i in range(m):
            if d[i] > tol:
                ratio = xB[i] / d[i]
                if best_ratio is None or ratio < best_ratio - tol or (
                    abs(ratio - best_ratio) <= tol and (best_basis_idx is None or basis[i] < best_basis_idx)
                ):
                    best_ratio = ratio
                    leaving_row = i
                    best_basis_idx = basis[i]

        if leaving_row == -1:
            return LPStatus.UNBOUNDED, basis, None, it

        basis[leaving_row] = entering

    return LPStatus.ITERATION_LIMIT, basis, None, it


def solve_lp(model: Model, tol: float = 1e-7, max_iter: int = 5000,
             use_scaling: bool = True,
             scaling_threshold: float = DEFAULT_SCALING_THRESHOLD) -> LPResult:
    t0 = time.time()
    try:
        std = _StdForm(model, tol, use_scaling=use_scaling,
                       scaling_threshold=scaling_threshold)
    except NotImplementedError as e:
        return LPResult(status=LPStatus.NUMERICAL_FAILURE, verification_message=str(e))

    m, n = std.A.shape
    basis = list(std.basis)

    # ---- Phase 1: minimize sum of artificials ----
    phase1_cost = np.zeros(n)
    for a in std.artificial_col:
        phase1_cost[a] = 1.0
    allowed = np.ones(n, dtype=bool)  # all columns allowed in phase 1

    status, basis, x_full, it1 = _run_simplex_phase(std, phase1_cost, basis, allowed, max_iter, tol)
    if status != LPStatus.OPTIMAL:
        return LPResult(status=status, iterations=it1, phase1_iterations=it1,
                         runtime_sec=time.time() - t0,
                         verification_message="Phase 1 did not terminate optimally")

    phase1_obj = float(np.dot(phase1_cost, x_full))
    if phase1_obj > 1e-6:
        return LPResult(status=LPStatus.INFEASIBLE, iterations=it1, phase1_iterations=it1,
                         runtime_sec=time.time() - t0)

    # Try to drive any residual basic artificials (at ~0) out of the basis
    art_set = set(std.artificial_col)
    for row in range(m):
        if basis[row] in art_set:
            Bm = std.A[:, basis]
            try:
                Binv_row = gauss_solve_transpose(Bm, np.eye(m)[row], tol=tol)
            except SingularBasisError:
                continue
            replaced = False
            for j in range(n):
                if j in art_set or j in set(basis):
                    continue
                coeff = float(np.dot(Binv_row, std.A[:, j]))
                if abs(coeff) > tol:
                    basis[row] = j
                    replaced = True
                    break
            # if not replaced: row is redundant; artificial stays at 0, harmless

    # ---- Phase 2: minimize true objective, artificials barred ----
    phase2_cost = np.zeros(n)
    phase2_cost[:std.n_orig] = std.obj_scaled
    allowed2 = np.ones(n, dtype=bool)
    for a in std.artificial_col:
        allowed2[a] = False

    status2, basis2, x_full2, it2 = _run_simplex_phase(std, phase2_cost, basis, allowed2, max_iter, tol)
    total_it = it1 + it2

    if status2 != LPStatus.OPTIMAL:
        return LPResult(status=status2, iterations=total_it, phase1_iterations=it1,
                         phase2_iterations=it2, runtime_sec=time.time() - t0)

    # Recover original-space solution. Undo, in order: the cost scale (objective
    # only), the column scale (y_j = d_j * y_hat_j), the lower-bound shift.
    values = {}
    for j, vn in enumerate(std.var_names):
        values[vn] = float(x_full2[j] * std.col_scale[j] + std.lb[j])

    # Objective computed through the simplex's own scaled vector and then
    # unscaled -- deliberately a different arithmetic path from
    # verify_lp_solution's recompute over the returned values, so that the two
    # genuinely cross-check each other.
    raw_obj = float(np.dot(std.obj_scaled, x_full2[:std.n_orig])) / std.cost_scale
    obj = raw_obj + std.obj_offset

    result = LPResult(status=LPStatus.OPTIMAL, objective=obj, values=values,
                       iterations=total_it, phase1_iterations=it1, phase2_iterations=it2,
                       runtime_sec=time.time() - t0,
                       scaling_summary=std.scaling.summary())

    ok, msg = verify_lp_solution(model, result, tol=1e-5)
    result.verified_feasible = ok
    result.verification_message = msg
    if not ok:
        # Never report OPTIMAL for a solution that fails the independent
        # feasibility/objective re-check. The values are kept on the result for
        # debugging, but the STATUS must not claim optimality.
        result.status = LPStatus.NUMERICAL_FAILURE
        result.verification_message = f"REJECTED (failed independent verification): {msg}"
    return result


def verify_lp_solution(model: Model, result: LPResult, tol: float = 1e-5):
    """Independent re-check: bounds + constraint satisfaction + objective recompute."""
    if result.status != LPStatus.OPTIMAL:
        return False, f"No feasible solution to verify (status={result.status.value})"
    for vn, v in model.variables.items():
        val = result.values.get(vn, None)
        if val is None:
            return False, f"Missing value for variable {vn}"
        if val < v.lb - tol or val > v.ub + tol:
            return False, f"Variable {vn}={val} violates bounds [{v.lb},{v.ub}]"
    for c in model.constraints:
        lhs = sum(coeff * result.values[vn] for vn, coeff in c.coeffs.items())
        if c.sense == Sense.LE and lhs > c.rhs + tol:
            return False, f"Constraint {c.name} violated: {lhs} > {c.rhs}"
        if c.sense == Sense.GE and lhs < c.rhs - tol:
            return False, f"Constraint {c.name} violated: {lhs} < {c.rhs}"
        if c.sense == Sense.EQ and abs(lhs - c.rhs) > tol:
            return False, f"Constraint {c.name} violated: {lhs} != {c.rhs}"
    recompute = sum(model.variables[vn].obj_coeff * val for vn, val in result.values.items())
    if abs(recompute - result.objective) > max(tol, 1e-6 * abs(result.objective)):
        return False, f"Objective mismatch: reported {result.objective}, recomputed {recompute}"
    return True, "Feasibility and objective independently verified"
