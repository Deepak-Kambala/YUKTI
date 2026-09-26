#!/usr/bin/env bash
# Sovereign Optimization Engine -- full demonstration pipeline.
# Every number printed below comes from an actual execution of the code in
# this repository. Nothing is hard-coded or simulated.
set -e
cd "$(dirname "$0")"

echo "=================================================================="
echo " Sovereign Optimization Engine -- Full Demo"
echo "=================================================================="

echo ""
echo "[1/8] Checking Python environment..."
python3 -c "import numpy" 2>/dev/null || pip install numpy --break-system-packages -q
python3 -c "import pytest" 2>/dev/null || pip install pytest --break-system-packages -q
python3 -c "import matplotlib" 2>/dev/null || pip install matplotlib --break-system-packages -q
echo "    OK (numpy = arrays only; every linear solve is our own Gaussian elimination)"

echo ""
echo "[2/8] Running unit/integration test suite..."
echo "      (use 'python3 -m pytest tests/ -v' for the per-test listing)"
python3 -m pytest tests/ -q

echo ""
echo "[3/8] Running a single LP example via CLI..."
mkdir -p results/demo/lp
python3 -m sovereign_opt.cli --refinery small --outdir results/demo/lp

echo ""
echo "[4/8] Running a single MILP example via CLI..."
mkdir -p results/demo/milp
python3 -m sovereign_opt.cli --refinery small --integer --outdir results/demo/milp

echo ""
echo "[5/8] Running the full benchmark suite (15 instances)..."
python3 scripts/run_benchmarks.py

echo ""
echo "[6/8] Measuring the equilibration layer (A/B/C, same process, best-of-3)..."
python3 scripts/ab_scaling.py | tail -12

echo ""
echo "[7/8] Generating plots from real benchmark data..."
python3 scripts/plot_results.py

echo ""
echo "[8/8] Summary"
echo "=================================================================="
cat results/summaries/benchmark_summary.md
echo "=================================================================="
echo "Full per-instance results: results/benchmark_results.csv"
echo "Per-instance solution files: results/raw/*.json"
echo "Scaling A/B measurements:  results/summaries/scaling_ab.csv"
echo "Plots: results/summaries/runtime.png, results/summaries/bnb_nodes.png"
echo "Solver logs from CLI runs: results/demo/lp/solver.log, results/demo/milp/solver.log"
echo "=================================================================="
