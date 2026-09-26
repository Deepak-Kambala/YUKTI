"""Unit tests for the equilibration (scaling) layer in linalg/scaling.py."""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sovereign_opt.linalg.scaling import (compute_scaling, identity_scaling, cost_scale,
                                          auto_scaling, matrix_spread)


def _is_pow2(x):
    return abs(math.log2(x) - round(math.log2(x))) < 1e-12


def test_reduces_magnitude_spread():
    # one row, entries 1e-4 and 1e4 -> spread 1e8
    rows = [{0: 1e-4, 1: 1e4}]
    s = compute_scaling(rows, 2)
    assert s.spread_before >= 1e8 - 1
    assert s.spread_after < 4.0        # brought to O(1)
    assert s.spread_after < s.spread_before


def test_factors_are_powers_of_two():
    rows = [{0: 3.7e-5, 1: 8.1e3}, {0: 1.2e4, 1: 5e-6}]
    s = compute_scaling(rows, 2)
    for v in list(s.row) + list(s.col):
        assert v > 0.0 and _is_pow2(v)


def test_already_unit_matrix_is_left_alone():
    rows = [{0: 1.0, 1: 1.0}, {0: 1.0, 1: -1.0}]
    s = compute_scaling(rows, 2)
    assert all(abs(v - 1.0) < 1e-12 for v in s.row)
    assert all(abs(v - 1.0) < 1e-12 for v in s.col)
    assert abs(s.spread_after - 1.0) < 1e-12


def test_scaled_entries_are_near_one():
    rows = [{0: 1e-4, 1: 1e4}, {0: 1e-3, 1: 1e2}]
    s = compute_scaling(rows, 2)
    for i, r in enumerate(rows):
        for j, v in r.items():
            a = abs(v) * s.row[i] * s.col[j]
            assert 1e-2 < a < 1e2, (i, j, a)


def test_structural_zeros_and_empty_rows_are_safe():
    rows = [{}, {0: 0.0}, {1: 2.0}]      # empty row, explicit zero, normal row
    s = compute_scaling(rows, 2)
    assert abs(s.row[0] - 1.0) < 1e-12   # empty row: factor 1
    assert abs(s.row[1] - 1.0) < 1e-12   # all-zero row: factor 1
    assert all(v > 0.0 for v in s.row) and all(v > 0.0 for v in s.col)


def test_identity_scaling_is_noop():
    s = identity_scaling(3, 4)
    assert not s.applied
    assert list(s.row) == [1.0, 1.0, 1.0]
    assert list(s.col) == [1.0] * 4


def test_auto_scaling_skips_well_scaled_models():
    """A well-scaled model must be left bit-for-bit untouched (no behaviour change)."""
    rows = [{0: 1.0, 1: 3.0}, {0: 2.0, 1: 1.0}]
    s = auto_scaling(rows, 2)
    assert not s.applied
    assert all(v == 1.0 for v in s.row) and all(v == 1.0 for v in s.col)


def test_auto_scaling_engages_on_badly_scaled_models():
    rows = [{0: 1e-4, 1: 1e4}]
    s = auto_scaling(rows, 2)
    assert s.applied
    assert s.spread_after < s.spread_before


def test_auto_scaling_threshold_one_forces_scaling():
    rows = [{0: 1.0, 1: 3.0}, {0: 2.0, 1: 1.0}]
    forced = auto_scaling(rows, 2, threshold=1.0)
    assert forced.applied


def test_matrix_spread():
    assert abs(matrix_spread([{0: 2.0, 1: 8.0}], 2) - 4.0) < 1e-12
    assert matrix_spread([{}], 1) == 1.0


def test_cost_scale_centres_objective_magnitudes():
    import numpy as np
    c = np.array([1e4, -1e-7, 0.0])
    g = cost_scale(c)
    assert _is_pow2(g)
    scaled = [abs(v) * g for v in c if v != 0.0]
    # geometric mean of magnitudes brought within a couple of orders of 1
    assert max(scaled) < 1e7 and min(scaled) > 1e-7


def test_cost_scale_all_zero_objective():
    import numpy as np
    assert cost_scale(np.zeros(5)) == 1.0
