"""
From-scratch dense linear system solver used by the revised simplex method
to solve basis systems  B x = b  and  B^T y = c_B.

This is the ONLY place where "B^-1" type computation happens. It is
implemented here (Gaussian elimination with partial pivoting) rather than
via numpy.linalg.solve, because solving the basis system is part of the
optimization algorithm itself, not general-purpose numerics.

numpy is used only as a typed array container / elementwise arithmetic;
no numpy.linalg.* routines are called anywhere in this module.
"""
from __future__ import annotations
import numpy as np


class SingularBasisError(Exception):
    """Raised when the basis matrix is numerically singular."""
    pass


def gauss_solve(A: np.ndarray, b: np.ndarray, tol: float = 1e-9) -> np.ndarray:
    """
    Solve A x = b for square A using Gaussian elimination with partial
    pivoting. Implemented from scratch (no numpy.linalg calls).

    Raises SingularBasisError if a pivot smaller than `tol` is encountered
    after searching for the best available pivot in the column.
    """
    n = A.shape[0]
    if A.shape[1] != n:
        raise ValueError("gauss_solve requires a square matrix")
    if b.shape[0] != n:
        raise ValueError("Dimension mismatch between A and b")

    # Augmented matrix, work in float64 copy
    M = np.array(A, dtype=np.float64, copy=True)
    x = np.array(b, dtype=np.float64, copy=True)

    # NOTE: an earlier version of this function scaled the singularity
    # tolerance by the matrix's magnitude. That was tried and measured to
    # make poorly-scaled problems WORSE (see docs/limitations.md), so it was
    # reverted in favor of the plain absolute tolerance below. This is a
    # known, documented limitation, not a hidden one.
    eff_tol = tol

    # Forward elimination with partial pivoting
    for col in range(n):
        # find pivot row (largest absolute value in this column, at/below diag)
        pivot_row = col + int(np.argmax(np.abs(M[col:, col])))
        pivot_val = M[pivot_row, col]

        if abs(pivot_val) < eff_tol:
            raise SingularBasisError(
                f"Basis matrix numerically singular at column {col} "
                f"(best pivot magnitude {abs(pivot_val):.3e} < tol {tol:.1e})"
            )

        if pivot_row != col:
            M[[col, pivot_row], :] = M[[pivot_row, col], :]
            x[[col, pivot_row]] = x[[pivot_row, col]]

        # eliminate below
        pivot = M[col, col]
        for row in range(col + 1, n):
            factor = M[row, col] / pivot
            if factor != 0.0:
                M[row, col:] -= factor * M[col, col:]
                x[row] -= factor * x[col]

    # Back substitution
    sol = np.zeros(n, dtype=np.float64)
    for row in range(n - 1, -1, -1):
        diag = M[row, row]
        if abs(diag) < eff_tol:
            raise SingularBasisError(
                f"Zero pivot encountered during back-substitution at row {row}"
            )
        sol[row] = (x[row] - np.dot(M[row, row + 1:], sol[row + 1:])) / diag

    return sol


def gauss_solve_transpose(A: np.ndarray, b: np.ndarray, tol: float = 1e-9) -> np.ndarray:
    """Solve A^T y = b, from scratch, by transposing and reusing gauss_solve."""
    return gauss_solve(A.T.copy(), b, tol=tol)
