"""Validate Locust CSV results against performance thresholds (Phase 21).

Parses the ``*_stats.csv`` Locust writes with ``--csv`` and checks the
``Aggregated`` row against latency/error-rate budgets. Exit code 0 = within
budget, 1 = a threshold exceeded (or the CSV is missing). Used by the
*non-blocking* ``perf-smoke`` CI job, so a non-zero exit surfaces as a warning,
not a build failure.

Stdlib only (csv/sys/os/pathlib) per project rules. The stats CSV path defaults
to ``tests/performance/locust-results_stats.csv`` and can be overridden with the
``LOCUST_STATS_CSV`` env var or a CLI argument (handy for tests).
"""

import csv
import os
import sys
from pathlib import Path

THRESHOLDS = {
    "avg_response_time": 500.0,  # ms
    "error_rate": 5.0,  # %
    "p99_response_time": 2000.0,  # ms
}

DEFAULT_CSV = Path("tests/performance/locust-results_stats.csv")


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def check(csv_path: str | os.PathLike[str] | None = None) -> int:
    """Return 0 if all thresholds pass, else 1 (also prints the verdict)."""
    path = Path(csv_path) if csv_path else Path(os.getenv("LOCUST_STATS_CSV", DEFAULT_CSV))
    if not path.exists():
        print(f"WARNING: Locust CSV not found at {path} - smoke test may not have run")
        return 1

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    agg = next((r for r in rows if r.get("Name") == "Aggregated"), None)
    if agg is None:
        print("WARNING: no 'Aggregated' row in Locust CSV")
        return 1

    violations: list[str] = []

    avg_rt = _to_float(agg.get("Average Response Time"))
    if avg_rt > THRESHOLDS["avg_response_time"]:
        violations.append(
            f"Avg Response Time {avg_rt:.0f}ms > {THRESHOLDS['avg_response_time']:.0f}ms"
        )

    total = int(_to_float(agg.get("Request Count"), 0)) or 1
    fails = int(_to_float(agg.get("Failure Count"), 0))
    error_pct = (fails / total) * 100
    if error_pct > THRESHOLDS["error_rate"]:
        violations.append(f"Error Rate {error_pct:.1f}% > {THRESHOLDS['error_rate']:.1f}%")

    p99 = _to_float(agg.get("99%"))
    if p99 > THRESHOLDS["p99_response_time"]:
        violations.append(f"P99 {p99:.0f}ms > {THRESHOLDS['p99_response_time']:.0f}ms")

    if violations:
        print("FAIL: performance thresholds exceeded:")
        for v in violations:
            print(f"   - {v}")
        return 1

    print(f"PASS: all thresholds OK (avg={avg_rt:.0f}ms, err={error_pct:.1f}%, p99={p99:.0f}ms)")
    return 0


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(check(arg))


if __name__ == "__main__":
    main()
