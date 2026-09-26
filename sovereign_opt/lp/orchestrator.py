"""
Top-level orchestration: presolve -> LP solve -> postsolve -> independent
re-verification against the ORIGINAL model. This is the function that
should be used by the CLI/MILP layer rather than calling presolve and
solve_lp separately, because the objective value of a presolved-and-reduced
model is not directly meaningful once variables have been fixed/folded away
-- it must be recomputed on the postsolved, original-space solution.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict
import time

from sovereign_opt.core.model import Model
from sovereign_opt.presolve.presolve import presolve, postsolve_values, PresolveLog
from sovereign_opt.lp.simplex import solve_lp, verify_lp_solution, LPResult, LPStatus
from sovereign_opt.linalg.scaling import DEFAULT_SCALING_THRESHOLD


@dataclass
class SolveReport:
    status: LPStatus
    objective: float
    values: Dict[str, float]
    presolve_log: PresolveLog
    orig_vars: int
    reduced_vars: int
    orig_cons: int
    reduced_cons: int
    lp_iterations: int
    runtime_sec: float
    verified_feasible: bool
    verification_message: str
    scaling_summary: str = ""


def solve_lp_with_presolve(model: Model, use_presolve: bool = True, tol: float = 1e-7,
                           use_scaling: bool = True,
                           scaling_threshold: float = DEFAULT_SCALING_THRESHOLD) -> SolveReport:
    t0 = time.time()
    orig_vars, orig_cons = model.num_vars(), model.num_constraints()

    if use_presolve:
        reduced, log = presolve(model, tol=1e-9)
    else:
        reduced, log = model.copy(), PresolveLog(original_var_names=list(model.var_order))

    if log.infeasible:
        return SolveReport(status=LPStatus.INFEASIBLE, objective=0.0, values={}, presolve_log=log,
                            orig_vars=orig_vars, reduced_vars=reduced.num_vars(), orig_cons=orig_cons,
                            reduced_cons=reduced.num_constraints(), lp_iterations=0,
                            runtime_sec=time.time() - t0, verified_feasible=False,
                            verification_message=log.infeasible_reason)

    lp_res = solve_lp(reduced, tol=tol, use_scaling=use_scaling,
                      scaling_threshold=scaling_threshold)

    if lp_res.status != LPStatus.OPTIMAL:
        return SolveReport(status=lp_res.status, objective=0.0, values={}, presolve_log=log,
                            orig_vars=orig_vars, reduced_vars=reduced.num_vars(), orig_cons=orig_cons,
                            reduced_cons=reduced.num_constraints(), lp_iterations=lp_res.iterations,
                            runtime_sec=time.time() - t0, verified_feasible=False, verification_message="")

    full_values = postsolve_values(model, log, lp_res.values)
    true_obj = sum(model.variables[vn].obj_coeff * val for vn, val in full_values.items())

    fake_result = LPResult(status=LPStatus.OPTIMAL, objective=true_obj, values=full_values)
    ok, msg = verify_lp_solution(model, fake_result, tol=1e-5)

    # Same rule as in simplex.solve_lp: a postsolved solution that fails the
    # independent re-check against the ORIGINAL model is not reported OPTIMAL.
    final_status = LPStatus.OPTIMAL if ok else LPStatus.NUMERICAL_FAILURE
    if not ok:
        msg = f"REJECTED (failed independent verification): {msg}"

    return SolveReport(status=final_status, objective=true_obj, values=full_values, presolve_log=log,
                        orig_vars=orig_vars, reduced_vars=reduced.num_vars(), orig_cons=orig_cons,
                        reduced_cons=reduced.num_constraints(), lp_iterations=lp_res.iterations,
                        runtime_sec=time.time() - t0, verified_feasible=ok, verification_message=msg,
                        scaling_summary=lp_res.scaling_summary)
