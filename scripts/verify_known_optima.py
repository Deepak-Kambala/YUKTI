"""
Independent re-derivation of every declared "known optimal" value in the
benchmark library -- WITHOUT the simplex.

Why this exists
---------------
`benchmarks/instances.py` attaches a `known_optimal` value to 8 instances, and
`scripts/run_benchmarks.py` reports "matched known optimum: 8/8". A reader is
entitled to ask where those 8 numbers came from. Originally they came from
hand-derivation (and one of them, the diet LP, was hand-derived WRONG the first
time -- see docs/results.md). Hand-derivation is not repository evidence.

This script re-derives each one by brute force in EXACT RATIONAL ARITHMETIC
(`fractions.Fraction`), using no floating point and none of this project's
solver code:

  * LP instances: enumerate every candidate vertex of the feasible region by
    taking all n-subsets of the constraint/bound hyperplanes, solving the n x n
    system exactly by Cramer's rule, discarding singular subsets and infeasible
    points, and taking the exact minimum objective over the survivors. For a
    bounded, nonempty polyhedron the LP optimum is attained at a vertex, so this
    is an exact optimum, not an approximation.

  * MILP instances: enumerate every integer point in the variable box and take
    the exact minimum over the feasible ones.

Boundedness certificate
-----------------------
Some instances leave variables with an infinite upper bound. Vertex enumeration
needs a bounded region, so an ARTIFICIAL box `x_j <= BIG` is added to those
columns. That is only legitimate if the artificial bound does not bind: the
script therefore checks that no coordinate of the winning vertex sits at BIG and
refuses to certify the instance if one does. A non-binding constraint cannot
change an optimum, so when the check passes the answer is the true LP optimum.

Exactness note
--------------
Model coefficients are Python floats. `Fraction(float)` is the EXACT binary
value of that float, so this script verifies the model precisely as the solver
receives it -- it does not quietly "clean up" 1e-5 into 1/100000. One
consequence is worth stating up front: for the ill-conditioned instances the
exact optimum of the float model is NOT the round decimal in `known_optimal`
(e.g. 50/Fraction(1e-4) is not exactly 500000, because 1e-4 is not exactly
1/10000 in binary). The declared value is therefore accepted when it is the
correctly-rounded double of the exact optimum, and the exact rational and the
relative difference are both printed so the reader can see which instances are
exact and which are only exact-to-a-double.

Run:  python scripts/verify_known_optima.py
Exit: 0 if every declared known optimum is the correctly-rounded double of the
      exact optimum, 1 otherwise.
"""
from __future__ import annotations
import os
import sys
from fractions import Fraction
from itertools import combinations, product

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sovereign_opt.benchmarks.instances import get_instances
from sovereign_opt.core.model import Sense, VarType, INF

# Artificial bound for columns with no finite upper bound. Only ever used to
# make vertex enumeration well-posed; the script fails loudly if it binds.
BIG = Fraction(10) ** 12


# ---------------------------------------------------------------------------
# exact linear algebra (Fractions only -- no numpy, no float)
# ---------------------------------------------------------------------------

def _det(mat):
    """Exact determinant by Gaussian elimination over Fraction."""
    n = len(mat)
    a = [row[:] for row in mat]
    det = Fraction(1)
    for col in range(n):
        piv = next((r for r in range(col, n) if a[r][col] != 0), None)
        if piv is None:
            return Fraction(0)
        if piv != col:
            a[col], a[piv] = a[piv], a[col]
            det = -det
        det *= a[col][col]
        inv = Fraction(1) / a[col][col]
        for r in range(col + 1, n):
            if a[r][col] == 0:
                continue
            f = a[r][col] * inv
            for c in range(col, n):
                a[r][c] -= f * a[col][c]
    return det


def _cramer(mat, rhs):
    """Exact solution of mat x = rhs, or None if singular."""
    d = _det(mat)
    if d == 0:
        return None
    n = len(mat)
    out = []
    for j in range(n):
        sub = [[rhs[r] if c == j else mat[r][c] for c in range(n)] for r in range(n)]
        out.append(_det(sub) / d)
    return out


# ---------------------------------------------------------------------------
# exact model view
# ---------------------------------------------------------------------------

def _rows(model, names):
    """All constraint + bound hyperplanes as (coeff_vector, sense, rhs, tag).

    Returns (rows, artificial_ub_index_by_var).
    """
    rows = []
    artificial = {}
    for c in model.constraints:
        vec = [Fraction(c.coeffs.get(n, 0.0)) for n in names]
        rows.append((vec, c.sense, Fraction(c.rhs), f"con:{c.name}"))
    for j, n in enumerate(names):
        v = model.variables[n]
        unit = [Fraction(1) if k == j else Fraction(0) for k in range(len(names))]
        if v.lb <= -INF:
            raise ValueError(f"{n} has no finite lower bound; this prototype rejects free vars")
        rows.append((unit, Sense.GE, Fraction(v.lb), f"lb:{n}"))
        if v.ub >= INF:
            artificial[n] = len(rows)
            rows.append((unit, Sense.LE, BIG, f"ub*:{n}"))
        else:
            rows.append((unit, Sense.LE, Fraction(v.ub), f"ub:{n}"))
    return rows, artificial


def _feasible(point, rows):
    for vec, sense, rhs, _ in rows:
        lhs = sum(a * x for a, x in zip(vec, point))
        if sense == Sense.LE and lhs > rhs:
            return False
        if sense == Sense.GE and lhs < rhs:
            return False
        if sense == Sense.EQ and lhs != rhs:
            return False
    return True


def _objective(model, names, point):
    return sum(Fraction(model.variables[n].obj_coeff) * x for n, x in zip(names, point))


# ---------------------------------------------------------------------------
# exact optima
# ---------------------------------------------------------------------------

def exact_lp_optimum(model):
    """(optimum, argmin, n_vertices, certificate_ok) by exact vertex enumeration."""
    names = list(model.var_order)
    n = len(names)
    rows, artificial = _rows(model, names)

    # equality rows must be active at every feasible point, so force them in
    eq_idx = [i for i, r in enumerate(rows) if r[1] == Sense.EQ]
    free_idx = [i for i in range(len(rows)) if i not in eq_idx]
    if len(eq_idx) > n:
        raise ValueError("more equality rows than variables")

    best, best_pt, seen = None, None, 0
    for combo in combinations(free_idx, n - len(eq_idx)):
        idx = list(eq_idx) + list(combo)
        mat = [rows[i][0] for i in idx]
        rhs = [rows[i][2] for i in idx]
        pt = _cramer(mat, rhs)
        if pt is None or not _feasible(pt, rows):
            continue
        seen += 1
        obj = _objective(model, names, pt)
        if best is None or obj < best:
            best, best_pt = obj, pt

    # boundedness certificate: no artificial bound may be active at the optimum
    cert = True
    if best_pt is not None:
        for name, ridx in artificial.items():
            if best_pt[names.index(name)] == rows[ridx][2]:
                cert = False
    return best, (dict(zip(names, best_pt)) if best_pt else None), seen, cert


def exact_milp_optimum(model):
    """(optimum, argmin, n_points) by exhaustive integer enumeration."""
    names = list(model.var_order)
    domains = []
    for n in names:
        v = model.variables[n]
        if v.vtype not in (VarType.INTEGER, VarType.BINARY):
            raise ValueError(f"{n} is continuous; exhaustive enumeration does not apply")
        if v.lb <= -INF or v.ub >= INF:
            raise ValueError(f"{n} has an infinite bound; exhaustive enumeration does not apply")
        domains.append([Fraction(k) for k in range(int(round(v.lb)), int(round(v.ub)) + 1)])

    rows, _ = _rows(model, names)
    best, best_pt, count = None, None, 0
    for pt in product(*domains):
        count += 1
        if not _feasible(pt, rows):
            continue
        obj = _objective(model, names, pt)
        if best is None or obj < best:
            best, best_pt = obj, list(pt)
    return best, (dict(zip(names, best_pt)) if best_pt else None), count


# ---------------------------------------------------------------------------

def main():
    print("Independent re-derivation of declared known optima")
    print("exact rational arithmetic, no simplex, no floating point")
    print("=" * 78)
    failures = 0
    checked = 0
    exact_hits = 0

    for inst in get_instances():
        if inst.known_optimal is None:
            continue
        model = inst.build()
        checked += 1
        try:
            if inst.problem_type == "MILP":
                opt, pt, work = exact_milp_optimum(model)
                cert, how = True, f"{work} integer points"
            else:
                opt, pt, work, cert = exact_lp_optimum(model)
                how = f"{work} feasible vertices"
        except ValueError as e:
            print(f"[SKIP  ] {inst.name:32s} {e}")
            failures += 1
            continue

        declared = Fraction(inst.known_optimal)
        exactly_equal = (opt == declared)
        same_double = (float(opt) == inst.known_optimal)
        if exactly_equal:
            exact_hits += 1

        if not cert:
            tag = "BOUND?"
        elif exactly_equal:
            tag = "EXACT"
        elif same_double:
            tag = "ULP"
        else:
            tag = "DIFFER"
        if not (same_double and cert):
            failures += 1

        print(f"[{tag:6s}] {inst.name:32s} exact -> double = {float(opt)!r:>16s}  "
              f"declared = {inst.known_optimal!r:>16s}  ({how})")
        if not exactly_equal:
            rel = float(abs(opt - declared) / abs(declared)) if declared != 0 else float("inf")
            print(f"          exact rational = {opt}")
            print(f"          not exactly equal to the declared decimal (rel. diff {rel:.3e});"
                  f" the float model's true optimum rounds to the declared double")
        if not same_double:
            print(f"          exact argmin: {pt}")
        if not cert:
            print("          artificial bound active at the optimum -- NOT certified bounded")

    print("=" * 78)
    print(f"{checked - failures}/{checked} declared known optima confirmed "
          f"(equal as IEEE doubles to the exact optimum).")
    print(f"{exact_hits}/{checked} are additionally exact in rational arithmetic; the rest "
          f"differ only because\nthe model's float coefficients are not the decimals they "
          f"are written as.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
