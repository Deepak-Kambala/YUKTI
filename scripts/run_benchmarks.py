"""
Benchmark runner: executes every instance in sovereign_opt.benchmarks.instances,
records real results to results/benchmark_results.csv and per-instance logs
under results/raw/, and prints a summary.

Run: python scripts/run_benchmarks.py
"""
from __future__ import annotations
import sys, os, csv, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sovereign_opt.benchmarks.instances import get_instances
from sovereign_opt.lp.orchestrator import solve_lp_with_presolve
from sovereign_opt.lp.simplex import LPStatus
from sovereign_opt.milp.branch_and_bound import solve_milp, MILPStatus

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")
os.makedirs(os.path.join(RESULTS_DIR, "raw"), exist_ok=True)
os.makedirs(os.path.join(RESULTS_DIR, "summaries"), exist_ok=True)


def run_all(time_limit=30.0, node_limit=20000):
    rows = []
    for inst in get_instances():
        model = inst.build()
        t0 = time.time()
        try:
            if model.is_milp():
                res = solve_milp(model, time_limit_sec=time_limit, node_limit=node_limit)
                status = res.status.value
                obj = res.objective
                verified = res.verified_feasible
                vmsg = res.verification_message
                iters_or_nodes = res.nodes_explored
                gap = res.mip_gap
            else:
                res = solve_lp_with_presolve(model)
                status = res.status.value
                obj = res.objective
                verified = res.verified_feasible
                vmsg = res.verification_message
                iters_or_nodes = res.lp_iterations
                gap = 0.0 if status == "OPTIMAL" else None
        except Exception as e:
            status, obj, verified, vmsg, iters_or_nodes, gap = "EXCEPTION", None, False, str(e), 0, None
        runtime = time.time() - t0

        known = inst.known_optimal
        matches_known = None
        if known is not None and obj is not None:
            matches_known = abs(obj - known) < 1e-4 * max(1.0, abs(known))

        row = dict(instance=inst.name, problem_type=inst.problem_type, variables=model.num_vars(),
                   constraints=model.num_constraints(), nonzeros=model.num_nonzeros(),
                   status=status, objective=obj, known_optimal=known, matches_known=matches_known,
                   runtime_sec=round(runtime, 4), iterations_or_nodes=iters_or_nodes,
                   mip_gap=gap, verified_feasible=verified, verification_message=vmsg, note=inst.note)
        rows.append(row)

        with open(os.path.join(RESULTS_DIR, "raw", f"{inst.name}.json"), "w") as f:
            json.dump(row, f, indent=2, default=str)

        print(f"[{inst.name:30s}] {inst.problem_type:5s} status={status:10s} obj={obj} "
              f"time={runtime:.3f}s verified={verified}")

    csv_path = os.path.join(RESULTS_DIR, "benchmark_results.csv")
    fieldnames = list(rows[0].keys())
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    return rows


def print_summary(rows):
    total = len(rows)
    optimal = sum(1 for r in rows if r["status"] == "OPTIMAL")
    infeasible = sum(1 for r in rows if r["status"] == "INFEASIBLE")
    node_or_time_limited = sum(1 for r in rows if r["status"] in ("NODE_LIMIT", "TIME_LIMIT", "FEASIBLE_NOT_PROVEN_OPTIMAL"))
    failed = sum(1 for r in rows if r["status"] in ("NUMERICAL_FAILURE", "EXCEPTION", "ITERATION_LIMIT"))
    verified_ok = sum(1 for r in rows if r["verified_feasible"])
    known_checked = [r for r in rows if r["known_optimal"] is not None]
    known_matches = sum(1 for r in known_checked if r["matches_known"])
    avg_runtime = sum(r["runtime_sec"] for r in rows) / total if total else 0.0

    summary = f"""# Benchmark Summary

Total instances: {total}
Optimal: {optimal}
Infeasible (correctly detected): {infeasible}
Feasible but not proven optimal (node/time limit hit): {node_or_time_limited}
Failed (numerical failure / exception): {failed}
Independently verified feasible+objective: {verified_ok} / {total}
Matched known/independently-derived optimal value: {known_matches} / {len(known_checked)}
Average runtime: {avg_runtime:.4f} sec

See benchmark_results.csv for the full per-instance table and results/raw/*.json for details.
"""
    with open(os.path.join(RESULTS_DIR, "summaries", "benchmark_summary.md"), "w") as f:
        f.write(summary)
    print("\n" + summary)


if __name__ == "__main__":
    rows = run_all()
    print_summary(rows)
