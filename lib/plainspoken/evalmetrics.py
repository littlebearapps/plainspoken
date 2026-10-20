"""Judge-validation metrics (Phase 6 evals): confusion counts, Wilson intervals, majority vote and Fleiss'
kappa. Pure functions, standard library only.

A judge's answer is a label or None. None is an **error** (the call failed, or the reply couldn't be scored): it is
counted on its own and is never a pass or a fail. Rates are reported with a 95% Wilson score interval, which stays
inside [0, 1] and behaves on small counts, where the golden set lives. There is no composite score."""
from __future__ import annotations

import math
from collections import Counter


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval for k successes in n trials; (0.0, 1.0) when n is 0 (nothing is known)."""
    if not (isinstance(k, int) and isinstance(n, int)) or k < 0 or n < 0 or k > n:
        raise ValueError(f"wilson needs 0 <= k <= n, got k={k!r}, n={n!r}")
    if n == 0:
        return 0.0, 1.0
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return lo, hi


def confusion(pairs: list[tuple[str, str | None]], positive: str) -> dict:
    """Counts for (truth, answer) pairs: `tp fn tn fp` for answers given, `errors` for answers that are None, and
    `n`, every pair. An answer that isn't `positive` counts as the negative label."""
    out = {"tp": 0, "fn": 0, "tn": 0, "fp": 0, "errors": 0, "n": len(pairs)}
    for truth, answer in pairs:
        if answer is None:
            out["errors"] += 1
        elif truth == positive:
            out["tp" if answer == positive else "fn"] += 1
        else:
            out["fp" if answer == positive else "tn"] += 1
    return out


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"value": k / n if n else None, "k": k, "n": n, "ci": [lo, hi]}


def rates(conf: dict) -> dict:
    """`tpr` (caught / positives), `tnr` (cleared / negatives) and `precision` (right / flagged), each
    `{value, k, n, ci}`. Errors are in no denominator. A zero denominator gives value None and ci [0, 1]."""
    tp, fn, tn, fp = conf["tp"], conf["fn"], conf["tn"], conf["fp"]
    return {"tpr": _rate(tp, tp + fn), "tnr": _rate(tn, tn + fp), "precision": _rate(tp, tp + fp)}


def majority(votes: list[str | None]) -> str | None:
    """The label with the most votes, errors (None) not voting. A tie for the most, or no label at all, is None."""
    counts = Counter(v for v in votes if v is not None).most_common()
    if not counts or (len(counts) > 1 and counts[0][1] == counts[1][1]):
        return None
    return counts[0][0]


def fleiss_kappa(table: list[list[int]]) -> float:
    """Fleiss' kappa for a subjects × categories table of rating counts; every row sums to the same number of
    raters (at least 2). Full agreement on a single category (no chance term to beat) is 1.0. ValueError for an
    empty or uneven table."""
    if not table or not table[0]:
        raise ValueError("fleiss_kappa needs at least one subject and one category")
    width = len(table[0])
    raters = sum(table[0])
    if raters < 2:
        raise ValueError("fleiss_kappa needs at least 2 raters per subject")
    for row in table:
        if len(row) != width or sum(row) != raters or any(c < 0 for c in row):
            raise ValueError("every row of a fleiss_kappa table needs the same categories and the same raters")
    subjects = len(table)
    p_j = [sum(row[j] for row in table) / (subjects * raters) for j in range(width)]
    p_i = [(sum(c * c for c in row) - raters) / (raters * (raters - 1)) for row in table]
    p_bar = sum(p_i) / subjects
    p_e = sum(p * p for p in p_j)
    if p_e >= 1.0:
        return 1.0
    return (p_bar - p_e) / (1 - p_e)
