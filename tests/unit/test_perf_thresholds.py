"""Unit tests for the Locust threshold checker (Phase 21).

Loads ``tests/performance/check_thresholds.py`` (not a package; loaded by path)
and feeds it synthetic Locust ``*_stats.csv`` files to verify the verdict and
exit code. Pure stdlib, fully offline.
"""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "performance" / "check_thresholds.py"

# Modern Locust stats CSV header (the columns the checker reads).
_HEADER = [
    "Type",
    "Name",
    "Request Count",
    "Failure Count",
    "Median Response Time",
    "Average Response Time",
    "Min Response Time",
    "Max Response Time",
    "Average Content Size",
    "Requests/s",
    "Failures/s",
    "50%",
    "66%",
    "75%",
    "80%",
    "90%",
    "95%",
    "98%",
    "99%",
    "99.9%",
    "100%",
]


def _load_checker():
    spec = importlib.util.spec_from_file_location("iigp_check_thresholds", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_csv(tmp_path, *, avg=100, req=1000, fails=0, p99=300) -> Path:
    path = tmp_path / "locust-results_stats.csv"
    row = {col: "0" for col in _HEADER}
    row.update(
        {
            "Type": "",
            "Name": "Aggregated",
            "Request Count": str(req),
            "Failure Count": str(fails),
            "Average Response Time": str(avg),
            "99%": str(p99),
        }
    )
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_HEADER)
        writer.writeheader()
        # A per-endpoint row plus the Aggregated row, like real Locust output.
        writer.writerow({**{c: "0" for c in _HEADER}, "Name": "GET /health"})
        writer.writerow(row)
    return path


@pytest.fixture()
def checker():
    return _load_checker()


@pytest.mark.unit
def test_all_thresholds_pass(checker, tmp_path, capsys):
    path = _write_csv(tmp_path, avg=120, req=1000, fails=0, p99=400)
    assert checker.check(path) == 0
    assert "PASS" in capsys.readouterr().out


@pytest.mark.unit
def test_avg_response_time_exceeded(checker, tmp_path, capsys):
    path = _write_csv(tmp_path, avg=750, p99=400)
    assert checker.check(path) == 1
    out = capsys.readouterr().out
    assert "Avg Response Time" in out


@pytest.mark.unit
def test_error_rate_exceeded(checker, tmp_path, capsys):
    path = _write_csv(tmp_path, req=100, fails=10)  # 10% > 5%
    assert checker.check(path) == 1
    assert "Error Rate" in capsys.readouterr().out


@pytest.mark.unit
def test_p99_exceeded(checker, tmp_path, capsys):
    path = _write_csv(tmp_path, p99=2500)
    assert checker.check(path) == 1
    assert "P99" in capsys.readouterr().out


@pytest.mark.unit
def test_missing_csv_returns_one(checker, tmp_path, capsys):
    missing = tmp_path / "nope_stats.csv"
    assert checker.check(missing) == 1
    assert "not found" in capsys.readouterr().out


@pytest.mark.unit
def test_no_aggregated_row(checker, tmp_path, capsys):
    path = tmp_path / "locust-results_stats.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_HEADER)
        writer.writeheader()
        writer.writerow({**{c: "0" for c in _HEADER}, "Name": "GET /health"})
    assert checker.check(path) == 1
    assert "Aggregated" in capsys.readouterr().out


@pytest.mark.unit
def test_boundary_not_exceeded(checker, tmp_path):
    # Exactly at the threshold must NOT count as a violation (strict >).
    path = _write_csv(tmp_path, avg=500, p99=2000, req=100, fails=5)  # 5% == limit
    assert checker.check(path) == 0
