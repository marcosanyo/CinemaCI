"""Cinema CI — Regression Detection and Result Summarizer.

Detects regressions by comparing current test results against baseline builds.
A regression occurs when a test that previously passed in baseline fails in current.
"""

from __future__ import annotations

from app.models import TestResult, TestStatus


def detect_regressions(
    current_results: list[TestResult],
    baseline_results: list[TestResult],
) -> list[TestResult]:
    """Detects regressions by comparing current test results with baseline.

    A test is classified as a REGRESSION if it passed in baseline but fails in current.
    Evaluator API infrastructure errors remain classified as FAIL rather than content regressions.

    Args:
        current_results: Test results for the current build.
        baseline_results: Test results for the baseline build.

    Returns:
        Updated current test results with REGRESSION status assigned where applicable.
    """
    baseline_map = {f"{r.test_id}:{r.scope}": r for r in baseline_results}

    for current in current_results:
        if current.status == TestStatus.FAIL:
            if current.observed and current.observed.startswith("Evaluation error:"):
                continue
            key = f"{current.test_id}:{current.scope}"
            baseline_match = baseline_map.get(key)
            if baseline_match and baseline_match.status == TestStatus.PASS:
                current.status = TestStatus.REGRESSION

    return current_results


def summarize_results(results: list[TestResult]) -> dict[str, int]:
    """Summarizes test results by status counts.

    Args:
        results: List of evaluated TestResult objects.

    Returns:
        Dictionary mapping status names to count totals.
    """
    summary = {
        "total": len(results),
        "pass": 0,
        "fail": 0,
        "regression": 0,
        "unknown": 0,
    }

    for r in results:
        if r.status == TestStatus.PASS:
            summary["pass"] += 1
        elif r.status == TestStatus.FAIL:
            summary["fail"] += 1
        elif r.status == TestStatus.REGRESSION:
            summary["regression"] += 1
        elif r.status == TestStatus.UNKNOWN:
            summary["unknown"] += 1

    return summary

