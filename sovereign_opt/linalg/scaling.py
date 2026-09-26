"""
Automatic matrix equilibration (scaling) for the LP constraint matrix.

Why this module exists
----------------------
The revised simplex in `lp/simplex.py` rejects a basis when Gaussian
elimination produces a pivot below an ABSOLUTE tolerance. On a badly scaled
model that test misfires: e.g. the basis

    [[1e-4, 1, 0],
     [0,    1, 0],
     [1e4,  0, 1]]

has det = 1e-4 (perfectly nonsingular), yet elimination yields a pivot of
1e-8 purely because the entries span 8 orders of magnitude -- so the basis is
wrongly declared singular and the solve returns NUMERICAL_FAILURE.

An earlier attempt fixed this by scaling the *tolerance* by the matrix
magnitude; that was measured to make things worse (see docs/limitations.md)
and was reverted. The standard remedy, used by production simplex codes, is
to scale the *matrix* instead: find positive row factors r_i and column
factors d_j so that the scaled entries r_i * a_ij * d_j are all close to 1 in
magnitude. Then the absolute pivot tolerance means what it was meant to mean.

Method: iterative geometric-mean equilibration. Each pass sets every row's
factor to 1/sqrt(min|a| * max|a|) over that row's nonzeros (so the row's
smallest and largest magnitudes straddle 1), then does the same per column.
Repeated until the magnitude spread stops improving. Factors are finally
rounded to powers of two, so multiplying by them is exact in binary floating
point and scaling introduces no rounding error of its own.

The transformation is exactly reversible and is undone in
`lp/simplex.py` when the solution is mapped back to original space:

    scaled column space:  y_j = d_j * y_hat_j
    scaled row i:         row i and its rhs both multiplied by r_i > 0
                          (r_i > 0 leaves <=, >=, = senses unchanged)

numpy is used here only as an array container for elementwise arithmetic; no
numpy.linalg routine is called.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence
import math

import numpy as np


@dataclass
class ScalingFactors:
    """Row/column factors plus honest before/after conditioning statistics."""

    row: np.ndarray            # length m, all > 0
    col: np.ndarray            # length n, all > 0
    spread_before: float       # max|a| / min|a| over nonzeros, before scaling
    spread_after: float        # same ratio after scaling
    passes: int                # equilibration passes actually performed
    applied: bool = True       # False => factors are all 1.0 (no transformation)
    reason: str = ""

    def summary(self) -> str:
        if not self.applied:
            return f"scaling: not applied ({self.reason}; spread {self.spread_before:.3e})"
        return (f"scaling: magnitude spread {self.spread_before:.3e} -> "
                f"{self.spread_after:.3e} in {self.passes} pass(es)")


def _pow2(x: float) -> float:
    """Round a positive factor to the nearest power of two (exact in binary FP)."""
    if not math.isfinite(x) or x <= 0.0:
        return 1.0
    return float(2.0 ** round(math.log2(x)))


def _spread(rows: Sequence[Dict[int, float]], r: np.ndarray, c: np.ndarray) -> float:
    """max/min magnitude over all structural nonzeros of the scaled matrix."""
    lo, hi = math.inf, 0.0
    for i, coeffs in enumerate(rows):
        for j, v in coeffs.items():
            a = abs(v) * r[i] * c[j]
            if a > 0.0:
                lo = min(lo, a)
                hi = max(hi, a)
    if hi == 0.0 or not math.isfinite(lo):
        return 1.0
    return hi / lo


def identity_scaling(m: int, n: int, spread: float = 1.0,
                     reason: str = "disabled by caller") -> ScalingFactors:
    """No-op factors: used when scaling is switched off, or not needed."""
    return ScalingFactors(row=np.ones(m), col=np.ones(n),
                          spread_before=spread, spread_after=spread, passes=0,
                          applied=False, reason=reason)


# Default threshold above which equilibration is applied.
#
# Rationale (not a value fitted to our benchmark set): the simplex declares a
# basis singular when a pivot falls below an ABSOLUTE tolerance of 1e-7. In a
# matrix whose nonzero magnitudes span a ratio S centred near 1, elimination can
# legitimately produce entries around 1/S (the failing case in
# docs/limitations.md had S = 1e8 and produced a pivot of exactly 1e-8). Keeping
# 1/S at least ~3 orders of magnitude above the 1e-7 pivot floor gives
# S_max ~ 1e4. Models below that are left untouched, so their numerical path --
# and every previously validated result -- is bit-for-bit unchanged.
DEFAULT_SCALING_THRESHOLD = 1e4


def matrix_spread(rows: Sequence[Dict[int, float]], n_cols: int) -> float:
    """max/min nonzero magnitude of the unscaled matrix (1.0 if no nonzeros)."""
    return _spread(rows, np.ones(len(rows)), np.ones(n_cols))


def auto_scaling(rows: List[Dict[int, float]], n_cols: int,
                 threshold: float = DEFAULT_SCALING_THRESHOLD) -> ScalingFactors:
    """
    Equilibrate only models that actually need it.

    A well-scaled model gets identity factors (zero cost, zero behavioural
    change); a model whose magnitude spread exceeds `threshold` gets the full
    geometric-mean equilibration. Pass threshold=1.0 to force scaling always on.
    """
    m = len(rows)
    if m == 0 or n_cols == 0:
        return identity_scaling(m, n_cols, reason="empty matrix")
    spread = matrix_spread(rows, n_cols)
    if spread <= threshold:
        return identity_scaling(m, n_cols, spread=spread,
                                reason=f"already well scaled, threshold {threshold:.1e}")
    return compute_scaling(rows, n_cols)


def compute_scaling(rows: List[Dict[int, float]], n_cols: int,
                    max_passes: int = 20, improve_tol: float = 0.9) -> ScalingFactors:
    """
    Compute geometric-mean row/column scaling factors for the sparse matrix
    given as `rows` (row i -> {column index: coefficient}).

    Returns factors rounded to powers of two. Rows/columns that are entirely
    structurally zero get factor 1.0. Stops early when a pass fails to reduce
    the magnitude spread by at least `improve_tol` (i.e. no useful progress).
    """
    m = len(rows)
    r = np.ones(m, dtype=np.float64)
    c = np.ones(n_cols, dtype=np.float64)
    if m == 0 or n_cols == 0:
        return identity_scaling(m, n_cols, reason="empty matrix")

    # column -> list of (row, value), built once
    by_col: List[List[tuple]] = [[] for _ in range(n_cols)]
    for i, coeffs in enumerate(rows):
        for j, v in coeffs.items():
            if v != 0.0:
                by_col[j].append((i, v))

    spread_before = _spread(rows, r, c)
    spread = spread_before
    done = 0
    for _ in range(max_passes):
        # --- rows ---
        for i, coeffs in enumerate(rows):
            lo, hi = math.inf, 0.0
            for j, v in coeffs.items():
                a = abs(v) * c[j]
                if a > 0.0:
                    lo = min(lo, a)
                    hi = max(hi, a)
            if hi > 0.0 and math.isfinite(lo):
                r[i] = _pow2(1.0 / math.sqrt(lo * hi))

        # --- columns ---
        for j in range(n_cols):
            lo, hi = math.inf, 0.0
            for (i, v) in by_col[j]:
                a = abs(v) * r[i]
                if a > 0.0:
                    lo = min(lo, a)
                    hi = max(hi, a)
            if hi > 0.0 and math.isfinite(lo):
                c[j] = _pow2(1.0 / math.sqrt(lo * hi))

        done += 1
        new_spread = _spread(rows, r, c)
        if new_spread > improve_tol * spread:   # no meaningful further improvement
            spread = new_spread
            break
        spread = new_spread

    # Safety: never ship factors that made conditioning worse than doing nothing.
    if spread > spread_before:
        return identity_scaling(m, n_cols, spread=spread_before,
                                reason="equilibration did not improve conditioning")

    return ScalingFactors(row=r, col=c, spread_before=spread_before,
                          spread_after=spread, passes=done)


def cost_scale(scaled_obj: np.ndarray) -> float:
    """
    One uniform positive factor for the whole objective vector.

    The entering-variable test is `reduced_cost < -tol` with a fixed absolute
    tol, so it is only meaningful if objective coefficients are O(1). Scaling
    the objective by a single positive scalar cannot change the optimal
    solution set (it rescales all reduced costs by the same amount); it is
    undone exactly when the objective value is reported. The geometric mean
    of the nonzero magnitudes is used (rather than the max) so that both very
    large and very small cost coefficients stay above the tolerance.
    """
    mags = [abs(v) for v in scaled_obj if v != 0.0]
    if not mags:
        return 1.0
    log_mean = sum(math.log(v) for v in mags) / len(mags)
    return _pow2(1.0 / math.exp(log_mean))
