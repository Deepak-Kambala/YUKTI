"""
Sparse matrix representation for the constraint matrix A.

HONESTY NOTE: this module provides sparse *storage and access* (CSR-style,
implemented from scratch — no scipy.sparse is used) for the constraint
matrix, so that models with many zero coefficients don't pay a dense-memory
cost when being built and presolved. It is NOT a sparse factorization
library: the revised simplex solver in sovereign_opt/lp/simplex.py builds a
dense basis matrix B from the columns selected by the current basis and
solves it directly. This means the prototype does not currently exploit
sparsity inside the linear-algebra core of simplex itself -- documented as
a limitation in docs/limitations.md. Extending to a sparse LU-based basis
solve is listed in the roadmap.
"""
from __future__ import annotations
from typing import Dict, List, Tuple
import numpy as np


class SparseMatrixCSR:
    """Minimal from-scratch CSR (compressed sparse row) matrix."""

    def __init__(self, n_rows: int, n_cols: int):
        self.n_rows = n_rows
        self.n_cols = n_cols
        self._row_data: List[List[Tuple[int, float]]] = [[] for _ in range(n_rows)]

    def set(self, row: int, col: int, value: float):
        if value == 0.0:
            return
        self._row_data[row].append((col, value))

    def nnz(self) -> int:
        return sum(len(r) for r in self._row_data)

    def row(self, i: int) -> List[Tuple[int, float]]:
        return self._row_data[i]

    def to_dense(self) -> np.ndarray:
        M = np.zeros((self.n_rows, self.n_cols), dtype=np.float64)
        for i, entries in enumerate(self._row_data):
            for j, v in entries:
                M[i, j] += v
        return M

    @classmethod
    def from_model_constraints(cls, constraints, col_index: Dict[str, int]) -> "SparseMatrixCSR":
        mat = cls(len(constraints), len(col_index))
        for i, c in enumerate(constraints):
            for vn, coeff in c.coeffs.items():
                mat.set(i, col_index[vn], coeff)
        return mat
