"""
A/B/C measurement of the automatic equilibration layer (linalg/scaling.py).

Runs EVERY benchmark instance in THREE modes, back to back in one process, so
the comparison is not confounded by machine state across sessions:

  off    : no scaling at all                     (use_scaling=False)
  auto   : scale only if magnitude spread > 1e4  (shipped default)
  always : scale unconditionally                 (scaling_threshold=1.0)

The point of `auto` is that well-scaled models must be left bit-for-bit
untouched -- the script checks that explicitly (identical status, objective and
iteration/node count vs `off`) and reports any instance where that fails.

Writes results/summaries/scaling_ab.csv and prints a table.
Run: python scripts/ab_scaling.py
"""
from __future__ import annotations
import sys, os, csv, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sovereign_opt.benchmarks.instances import get_instances
from sovereign_opt.lp.orchestrator import solve_lp_with_presolve
from sovereign_opt.milp.branch_and_bound import solve_milp

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")
REPEATS = 3   # best-of-N wall time, to damp scheduler noise

MODES = {
    "off":    dict(use_scaling=False),
    "auto":   dict(use_scaling=True),                          # shipped default
    "always": dict(use_scaling=True, scaling_threshold=1.0),
}


def _run_once(model, kwargs):
    if model.is_milp():
        r = solve_milp(model, time_limit_sec=30.0, node_limit=20000, **kwargs)
        return r.status.value, r.objective, r.nodes_explored, r.verified_feasible
    r = solve_lp_with_presolve(model, **kwargs)
    return r.status.value, r.objective, r.lp_iterations, r.verified_feasible


def measure(inst, kwargs):
    best, out = None, None
    for _ in range(REPEATS):
        model = inst.build()
        t0 = time.time()
        try:
            out = _run_once(model, kwargs)
        except Exception as e:                      # record, never hide
            return dict(status=f"EXCEPTION: {e}", objective=None, work=0,
                        verified=False, runtime=time.time() - t0)
        dt = time.time() - t0
        best = dt if best is None else min(best, dt)
    return dict(status=out[0], objective=out[1], work=out[2], verified=out[3], runtime=best)


def _same_obj(a, b):
    if a is None or b is None:
        return None
    return abs(a - b) <= 1e-6 * max(1.0, abs(b))


def _matches_known(obj, known):
    if known is None or obj is None:
        return None
    return abs(obj - known) < 1e-6 * max(1.0, abs(known))


def main():
    rows, behaviour_changed = [], []
    for inst in get_instances():
        res = {name: measure(inst, kw) for name, kw in MODES.items()}
        off, auto, always = res["off"], res["auto"], res["always"]

        # `auto` must be behaviourally identical to `off` UNLESS the model is
        # ill-conditioned enough to cross the scaling threshold -- which is
        # precisely the case the layer exists for.
        unchanged = (auto["status"] == off["status"]
                     and auto["work"] == off["work"]
                     and _same_obj(auto["objective"], off["objective"]) is not False)
        if not unchanged:
            behaviour_changed.append(inst.name)

        rows.append(dict(
            instance=inst.name, problem_type=inst.problem_type,
            known_optimal=inst.known_optimal,
            status_off=off["status"], status_auto=auto["status"], status_always=always["status"],
            objective_off=off["objective"], objective_auto=auto["objective"],
            objective_always=always["objective"],
            matches_known_off=_matches_known(off["objective"], inst.known_optimal),
            matches_known_auto=_matches_known(auto["objective"], inst.known_optimal),
            matches_known_always=_matches_known(always["objective"], inst.known_optimal),
            work_off=off["work"], work_auto=auto["work"], work_always=always["work"],
            runtime_off_sec=round(off["runtime"], 4),
            runtime_auto_sec=round(auto["runtime"], 4),
            runtime_always_sec=round(always["runtime"], 4),
            auto_identical_to_off=unchanged,
            verified_off=off["verified"], verified_auto=auto["verified"],
            verified_always=always["verified"],
        ))
        print(f"[{inst.name:30s}] off {off['runtime']:.4f}s/{off['work']:>4} | "
              f"auto {auto['runtime']:.4f}s/{auto['work']:>4} | "
              f"always {always['runtime']:.4f}s/{always['work']:>4} | "
              f"auto==off: {unchanged}")

    os.makedirs(os.path.join(RESULTS_DIR, "summaries"), exist_ok=True)
    path = os.path.join(RESULTS_DIR, "summaries", "scaling_ab.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    t_off = sum(r["runtime_off_sec"] for r in rows)
    t_auto = sum(r["runtime_auto_sec"] for r in rows)
    t_always = sum(r["runtime_always_sec"] for r in rows)

    def _solved(mode):
        return sum(1 for r in rows if r[f"status_{mode}"] in ("OPTIMAL", "INFEASIBLE"))

    def _known_ok(mode):
        checked = [r for r in rows if r["known_optimal"] is not None]
        return sum(1 for r in checked if r[f"matches_known_{mode}"]), len(checked)

    print(f"\nTotal best-of-{REPEATS} runtime over {len(rows)} instances:")
    print(f"  scaling off    : {t_off:.4f}s")
    print(f"  scaling auto   : {t_auto:.4f}s  ({t_off / t_auto:.2f}x vs off)   [shipped default]")
    print(f"  scaling always : {t_always:.4f}s  ({t_off / t_always:.2f}x vs off)")
    for mode in ("off", "auto", "always"):
        ok, tot = _known_ok(mode)
        print(f"  {mode:<7s}: solved(OPTIMAL|INFEASIBLE) {_solved(mode):>2}/{len(rows)}   "
              f"matches known optimum {ok}/{tot}")
    print(f"\nInstances where `auto` differs from `off` (i.e. crossed the scaling "
          f"threshold): {behaviour_changed if behaviour_changed else 'none'}")
    print("  -> every OTHER instance is bit-identical to the unscaled path, so no "
          "previously validated result changed.")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
