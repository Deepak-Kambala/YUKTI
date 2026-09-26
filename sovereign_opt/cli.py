"""
CLI entry point.

Usage:
    python -m sovereign_opt.cli problem.mps
    python -m sovereign_opt.cli --demo-lp
    python -m sovereign_opt.cli --demo-milp
    python -m sovereign_opt.cli --refinery small|medium|large [--integer]

Produces terminal output plus solution.csv / solution.json / solver.log
in the given --outdir (default: current directory).
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

from sovereign_opt.core.model import Model
from sovereign_opt.lp.orchestrator import solve_lp_with_presolve
from sovereign_opt.lp.simplex import LPStatus
from sovereign_opt.milp.branch_and_bound import solve_milp, MILPStatus
from sovereign_opt.io.mps_format import read_mps
from sovereign_opt.industrial.refinery import generate_refinery_instance


BANNER = "=" * 70 + "\nSovereign Optimization Engine (prototype)\n" + "=" * 70


def _log(logfile, msg):
    print(msg)
    if logfile:
        logfile.write(msg + "\n")


def run_problem(model: Model, outdir: Path, time_limit: float = 60.0, node_limit: int = 20000):
    outdir.mkdir(parents=True, exist_ok=True)
    log_path = outdir / "solver.log"
    logf = open(log_path, "w")

    is_milp = model.is_milp()
    ptype = "MILP" if is_milp else "LP"

    _log(logf, BANNER)
    _log(logf, f"Problem: {model.name}")
    _log(logf, f"Type: {ptype}")
    _log(logf, f"Variables: {model.num_vars()}")
    _log(logf, f"Constraints: {model.num_constraints()}")
    _log(logf, f"Integer variables: {model.num_integer_vars()}")
    _log(logf, f"Nonzeros: {model.num_nonzeros()}")

    t0 = time.time()
    if is_milp:
        result = solve_milp(model, time_limit_sec=time_limit, node_limit=node_limit)
        _log(logf, "")
        _log(logf, f"LP Relaxation Objective: {result.lp_relaxation_objective}")
        _log(logf, "")
        _log(logf, "Branch & Bound")
        _log(logf, f"  Nodes explored: {result.nodes_explored}")
        _log(logf, f"  Incumbent: {result.objective}")
        _log(logf, f"  Best bound: {result.best_bound}")
        _log(logf, f"  MIP Gap: {result.mip_gap * 100:.4f}%" if result.mip_gap is not None else "  MIP Gap: n/a")
        if result.abandoned_nodes:
            _log(logf, f"  WARNING: {result.abandoned_nodes} node(s) whose LP relaxation did "
                        f"not solve were left unexplored; optimality is NOT proven.")
        status = result.status.value
        objective = result.objective
        values = result.values
        verified = result.verified_feasible
        vmsg = result.verification_message
    else:
        result = solve_lp_with_presolve(model)
        _log(logf, "")
        _log(logf, f"Presolve  Variables: {model.num_vars()} -> {result.reduced_vars}   "
                    f"Constraints: {model.num_constraints()} -> {result.reduced_cons}")
        _log(logf, f"LP Iterations: {result.lp_iterations}")
        if result.scaling_summary:
            # summary() already starts with "scaling: "; only the first letter is
            # changed (str.capitalize would lowercase the rest, e.g. exponents)
            s = result.scaling_summary
            _log(logf, s[:1].upper() + s[1:])
        status = result.status.value
        objective = result.objective
        values = result.values
        verified = result.verified_feasible
        vmsg = result.verification_message

    runtime = time.time() - t0
    _log(logf, "")
    _log(logf, f"Status: {status}   Objective: {objective}   Time: {runtime:.3f} seconds")
    _log(logf, f"Independent verification: {'PASSED' if verified else 'FAILED'} -- {vmsg}")
    _log(logf, "=" * 70)

    # write outputs
    if values:
        with open(outdir / "solution.csv", "w") as f:
            f.write("variable,value\n")
            for vn, val in values.items():
                f.write(f"{vn},{val}\n")
    with open(outdir / "solution.json", "w") as f:
        json.dump({
            "problem": model.name, "type": ptype, "status": status,
            "objective": objective, "runtime_sec": runtime,
            "verified_feasible": verified, "verification_message": vmsg,
            "values": values,
        }, f, indent=2)

    logf.close()
    return status, objective, runtime, verified


def main(argv=None):
    p = argparse.ArgumentParser(description="Sovereign Optimization Engine CLI")
    p.add_argument("problem_file", nargs="?", help="Path to an MPS file")
    p.add_argument("--refinery", choices=["small", "medium", "large"], help="Generate synthetic refinery instance")
    p.add_argument("--integer", action="store_true", help="Use integer-batch refinery variant")
    p.add_argument("--outdir", default=".", help="Output directory for solution files")
    p.add_argument("--time-limit", type=float, default=60.0)
    p.add_argument("--node-limit", type=int, default=20000)
    args = p.parse_args(argv)

    outdir = Path(args.outdir)

    if args.problem_file:
        model = read_mps(args.problem_file)
        model.name = Path(args.problem_file).stem
    elif args.refinery:
        sizes = {"small": dict(n_crudes=3, n_products=2), "medium": dict(n_crudes=6, n_products=4),
                  "large": dict(n_crudes=12, n_products=8)}
        params = sizes[args.refinery]
        if args.integer:
            model = generate_refinery_instance(**params, seed=42, integer_batches=True, batch_unit=50)
        else:
            model = generate_refinery_instance(**params, seed=42)
    else:
        p.print_help()
        return 1

    run_problem(model, outdir, time_limit=args.time_limit, node_limit=args.node_limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
