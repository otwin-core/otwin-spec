"""The checks a conformant implementation must pass.

Design note — why the checks live here and not in each implementation
---------------------------------------------------------------------

An implementation is asked only to *run a scenario and report numbers*:
trajectories, energies, matrices at sample states. It is never asked to judge
itself. All judgement happens in this module, in one language, from one
source.

That split is what makes the suite meaningful across languages. If the MATLAB
binding checked its own passivity with MATLAB code, a bug in the check would
hide a bug in the model. Here, MATLAB reports an energy trace and this module
decides whether it is monotone — the same code path that judges Python and
Julia.

Every check returns a :class:`CheckResult` carrying the measured value, so a
failure report says *how far off* rather than merely "failed".
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

__all__ = ["CheckResult", "run_check", "CHECK_KINDS"]


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one check.

    Attributes:
        check_id: Identifier from the fixture.
        kind: Which check was run.
        passed: Whether it passed.
        measured: The number actually observed, for reporting.
        tolerance: The tolerance applied.
        detail: Human-readable explanation, always populated on failure.
        closed_form: The analytic statement being verified, copied from the
            fixture so a failure report is self-contained.
        skipped: True when the implementation did not report the quantity this
            check needs. A skip is not a pass and is counted separately.
    """

    check_id: str
    kind: str
    passed: bool
    measured: float | None = None
    tolerance: float | None = None
    detail: str = ""
    closed_form: str | None = None
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "kind": self.kind,
            "status": "skip" if self.skipped else ("pass" if self.passed else "fail"),
            "measured": self.measured,
            "tolerance": self.tolerance,
            "detail": self.detail,
            "closed_form": self.closed_form,
        }


def _finite(xs: Any) -> bool:
    """True when every leaf of a nested list is a finite number."""
    if isinstance(xs, (int, float)):
        return math.isfinite(xs)
    if isinstance(xs, (list, tuple)):
        return all(_finite(v) for v in xs)
    return False


def _flat(xs: Any) -> list[float]:
    """Flatten a nested list of numbers."""
    out: list[float] = []
    if isinstance(xs, (int, float)):
        out.append(float(xs))
    elif isinstance(xs, (list, tuple)):
        for v in xs:
            out.extend(_flat(v))
    return out


def _column(series: Any, index: int | None) -> list[float]:
    """Extract a scalar series, taking column ``index`` if the series is 2-D."""
    if not series:
        return []
    first = series[0]
    if isinstance(first, (list, tuple)):
        i = 0 if index is None else index
        return [float(row[i]) for row in series]
    return [float(v) for v in series]


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------


def _check_monotone_non_increasing(spec: dict, out: dict) -> CheckResult:
    q = spec.get("quantity", "energy")
    series = out.get(q)
    kind = spec["kind"]
    cid = spec["id"]
    cf = spec.get("closed_form")
    if series is None:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail=f"implementation reported no '{q}' series",
            closed_form=cf,
        )
    vals = _column(series, spec.get("index"))
    if len(vals) < 2:
        return CheckResult(
            cid,
            kind,
            False,
            detail=f"need >= 2 samples to check a trend, got {len(vals)}",
            closed_form=cf,
        )
    if not _finite(vals):
        return CheckResult(
            cid,
            kind,
            False,
            detail="series contains non-finite values: the run diverged. "
            "A diverged run is a failure, not a passive trajectory.",
            closed_form=cf,
        )
    tol = float(spec.get("abs_tol", 1e-9))
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    worst = max(diffs)
    ok = worst <= tol
    scale = max(abs(vals[0]), 1e-300)
    return CheckResult(
        cid,
        kind,
        ok,
        measured=worst,
        tolerance=tol,
        closed_form=cf,
        detail=(
            ""
            if ok
            else (
                f"{q} increased by {worst:.6g} at its worst step "
                f"({worst / scale:.3%} of the initial value); tolerance {tol:.3g}. "
                f"Energy was created, which a port-Hamiltonian structure forbids."
            )
        ),
    )


def _check_final_value(spec: dict, out: dict) -> CheckResult:
    q = spec.get("quantity", "state")
    series = out.get(q)
    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    if series is None:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail=f"implementation reported no '{q}' series",
            closed_form=cf,
        )
    vals = _column(series, spec.get("index"))
    if not vals:
        return CheckResult(cid, kind, False, detail="empty series", closed_form=cf)
    got, expected = vals[-1], float(spec["expected"])
    if not math.isfinite(got):
        return CheckResult(
            cid, kind, False, measured=got, detail="final value is not finite", closed_form=cf
        )
    if "rel_tol" in spec:
        tol = float(spec["rel_tol"])
        denom = abs(expected) if abs(expected) > 0 else 1.0
        err = abs(got - expected) / denom
        unit = "relative"
    else:
        tol = float(spec.get("abs_tol", 1e-9))
        err = abs(got - expected)
        unit = "absolute"
    ok = err <= tol
    return CheckResult(
        cid,
        kind,
        ok,
        measured=err,
        tolerance=tol,
        closed_form=cf,
        detail=(
            ""
            if ok
            else (
                f"final {q}[{spec.get('index', 0)}] = {got:.10g}, closed form = "
                f"{expected:.10g}; {unit} error {err:.3g} exceeds tolerance {tol:.3g}"
            )
        ),
    )


def _check_relative_drift(spec: dict, out: dict) -> CheckResult:
    q = spec.get("quantity", "energy")
    series = out.get(q)
    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    if series is None:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail=f"implementation reported no '{q}' series",
            closed_form=cf,
        )
    vals = _column(series, spec.get("index"))
    if len(vals) < 2:
        return CheckResult(cid, kind, False, detail="need >= 2 samples", closed_form=cf)
    if not _finite(vals):
        return CheckResult(
            cid, kind, False, detail="series contains non-finite values", closed_form=cf
        )
    start = vals[0]
    if abs(start) < 1e-300:
        return CheckResult(
            cid,
            kind,
            False,
            detail="initial value is zero; relative drift undefined",
            closed_form=cf,
        )
    drift = abs(vals[-1] - start) / abs(start)
    tol = float(spec["max_drift"])
    ok = drift <= tol
    return CheckResult(
        cid,
        kind,
        ok,
        measured=drift,
        tolerance=tol,
        closed_form=cf,
        detail=(
            ""
            if ok
            else (f"{q} drifted {drift:.3%} over the run; the fixture allows {tol:.3%}")
        ),
    )


def _check_non_negative(spec: dict, out: dict) -> CheckResult:
    q = spec.get("quantity")
    series = out.get(q)
    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    if series is None:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail=f"implementation reported no '{q}'",
            closed_form=cf,
        )
    vals = _flat(series)
    if not vals:
        return CheckResult(cid, kind, False, detail="empty series", closed_form=cf)
    if not _finite(vals):
        return CheckResult(cid, kind, False, detail="non-finite values", closed_form=cf)
    tol = float(spec.get("abs_tol", 1e-12))
    worst = min(vals)
    ok = worst >= -tol
    return CheckResult(
        cid,
        kind,
        ok,
        measured=worst,
        tolerance=tol,
        closed_form=cf,
        detail=(
            ""
            if ok
            else (
                f"{q} reached {worst:.6g}, below the permitted -{tol:.3g}. "
                f"For entropy production this is a second-law violation."
            )
        ),
    )


def _check_lower_bound(spec: dict, out: dict) -> CheckResult:
    q = spec.get("quantity", "state")
    series = out.get(q)
    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    if series is None:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail=f"implementation reported no '{q}'",
            closed_form=cf,
        )
    vals = _column(series, spec.get("index"))
    if not vals:
        return CheckResult(cid, kind, False, detail="empty series", closed_form=cf)
    if not _finite(vals):
        return CheckResult(
            cid, kind, False, closed_form=cf, detail=f"{q} contains non-finite values"
        )
    bound = float(spec["bound"])
    worst = min(vals)
    ok = worst >= bound
    return CheckResult(
        cid,
        kind,
        ok,
        measured=worst,
        tolerance=bound,
        closed_form=cf,
        detail="" if ok else f"{q} reached {worst:.6g}, below the bound {bound:.6g}",
    )


def _matrices(out: dict, name: str) -> list[list[list[float]]] | None:
    m = out.get("matrices")
    if not isinstance(m, dict):
        return None
    return m.get(name)


def _check_matrix_skew(spec: dict, out: dict) -> CheckResult:
    name = spec.get("matrix", "J")
    mats = _matrices(out, name)
    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    if not mats:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail=f"implementation reported no '{name}' matrices",
            closed_form=cf,
        )
    if not _finite(mats):
        return CheckResult(
            cid,
            kind,
            False,
            closed_form=cf,
            detail=f"{name} contains non-finite values. Python's max() and min() "
            f"silently swallow NaN, so this must be rejected explicitly rather "
            f"than compared.",
        )
    tol = float(spec.get("abs_tol", 1e-12))
    worst = 0.0
    for M in mats:
        n = len(M)
        for i in range(n):
            for j in range(n):
                worst = max(worst, abs(M[i][j] + M[j][i]))
    ok = worst <= tol
    return CheckResult(
        cid,
        kind,
        ok,
        measured=worst,
        tolerance=tol,
        closed_form=cf,
        detail=(
            ""
            if ok
            else (
                f"max |{name} + {name}^T| = {worst:.6g} > {tol:.3g}. "
                f"{name} is not skew-symmetric, so the interconnection is not lossless "
                f"and the power balance does not hold."
            )
        ),
    )


def _min_eigenvalue_symmetric(M: list[list[float]]) -> float:
    """Smallest eigenvalue of the symmetric part, by Jacobi rotation.

    Implemented without NumPy so this module stays dependency-free and can be
    transliterated into the reference documentation.
    """
    n = len(M)
    A = [[0.5 * (M[i][j] + M[j][i]) for j in range(n)] for i in range(n)]
    for _ in range(100):
        off = 0.0
        p = q = 0
        for i in range(n):
            for j in range(i + 1, n):
                if abs(A[i][j]) > off:
                    off, p, q = abs(A[i][j]), i, j
        if off < 1e-14:
            break
        app, aqq, apq = A[p][p], A[q][q], A[p][q]
        theta = 0.5 * math.atan2(2.0 * apq, app - aqq) if app != aqq else math.pi / 4
        c, s = math.cos(theta), math.sin(theta)
        for k in range(n):
            akp, akq = A[k][p], A[k][q]
            A[k][p] = c * akp + s * akq
            A[k][q] = -s * akp + c * akq
        for k in range(n):
            apk, aqk = A[p][k], A[q][k]
            A[p][k] = c * apk + s * aqk
            A[q][k] = -s * apk + c * aqk
    return min(A[i][i] for i in range(n))


def _check_matrix_psd(spec: dict, out: dict) -> CheckResult:
    name = spec.get("matrix", "R")
    mats = _matrices(out, name)
    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    if not mats:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail=f"implementation reported no '{name}' matrices",
            closed_form=cf,
        )
    if not _finite(mats):
        return CheckResult(
            cid,
            kind,
            False,
            closed_form=cf,
            detail=f"{name} contains non-finite values. Python's max() and min() "
            f"silently swallow NaN, so this must be rejected explicitly rather "
            f"than compared.",
        )
    tol = float(spec.get("abs_tol", 1e-12))
    worst = float("inf")
    for M in mats:
        worst = min(worst, _min_eigenvalue_symmetric(M))
    ok = worst >= -tol
    return CheckResult(
        cid,
        kind,
        ok,
        measured=worst,
        tolerance=tol,
        closed_form=cf,
        detail=(
            ""
            if ok
            else (
                f"min eigenvalue of {name} is {worst:.6g} < -{tol:.3g}. "
                f"{name} is not positive semidefinite, so the model can dissipate "
                f"negative energy — that is, create it."
            )
        ),
    )


def _check_matrix_equals(spec: dict, out: dict) -> CheckResult:
    name = spec.get("matrix", "J")
    mats = _matrices(out, name)
    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    if not mats:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail=f"implementation reported no '{name}' matrices",
            closed_form=cf,
        )
    if not _finite(mats):
        return CheckResult(
            cid,
            kind,
            False,
            closed_form=cf,
            detail=f"{name} contains non-finite values. Python's max() and min() "
            f"silently swallow NaN, so this must be rejected explicitly rather "
            f"than compared.",
        )
    target = float(spec.get("value", 0.0))
    tol = float(spec.get("abs_tol", 1e-12))
    worst = max((abs(v - target) for M in mats for v in _flat(M)), default=0.0)
    ok = worst <= tol
    return CheckResult(
        cid,
        kind,
        ok,
        measured=worst,
        tolerance=tol,
        closed_form=cf,
        detail="" if ok else f"max |{name} - {target:g}| = {worst:.6g} > {tol:.3g}",
    )


# --------------------------------------------------------------------------
# Manifest checks
# --------------------------------------------------------------------------


def _check_manifest_schema_valid(spec: dict, out: dict) -> CheckResult:
    from .schema import validate_manifest

    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    m = out.get("manifest")
    if m is None:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail="implementation reported no 'manifest'",
            closed_form=cf,
        )
    errors = validate_manifest(m)
    return CheckResult(
        cid,
        kind,
        not errors,
        closed_form=cf,
        detail="" if not errors else "; ".join(errors[:5]),
    )


def _check_manifest_roundtrip(spec: dict, out: dict) -> CheckResult:
    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    a, b = out.get("manifest"), out.get("manifest_roundtrip")
    if a is None or b is None:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail="need both 'manifest' and 'manifest_roundtrip'",
            closed_form=cf,
        )
    diffs = _dict_diff(a, b)
    return CheckResult(
        cid,
        kind,
        not diffs,
        closed_form=cf,
        detail=(
            ""
            if not diffs
            else f"round-trip changed {len(diffs)} field(s): {', '.join(diffs[:6])}"
        ),
    )


def _check_manifest_rejects_non_finite(spec: dict, out: dict) -> CheckResult:
    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    reported = out.get("rejects_non_finite")
    if reported is None:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            detail="implementation did not report 'rejects_non_finite'",
            closed_form=cf,
        )
    ok = reported is True
    return CheckResult(
        cid,
        kind,
        ok,
        closed_form=cf,
        detail=(
            ""
            if ok
            else (
                "implementation wrote a manifest containing NaN or Infinity. These are "
                "not valid JSON (RFC 8259) and are rejected by Julia's JSON3 and "
                "MATLAB's jsondecode, so the file would be unreadable from those "
                "languages."
            )
        ),
    )


def _dict_diff(a: Any, b: Any, path: str = "") -> list[str]:
    """Paths where two JSON-like structures differ."""
    out: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            p = f"{path}.{k}" if path else k
            if k not in a or k not in b:
                out.append(p)
            else:
                out.extend(_dict_diff(a[k], b[k], p))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}[len]")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out.extend(_dict_diff(x, y, f"{path}[{i}]"))
    elif isinstance(a, float) or isinstance(b, float):
        try:
            if not math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-15):
                out.append(path)
        except (TypeError, ValueError):
            out.append(path)
    elif a != b:
        out.append(path)
    return out


def _check_strictly_increasing(spec: dict, out: dict) -> CheckResult:
    """A quantity must actually rise, not merely fail to fall.

    Exists because ``non_negative`` on entropy production is far too weak: a
    model that conserves entropy reports a perfectly respectable non-negative
    sigma and creates none. Total entropy must go up.
    """
    q = spec.get("quantity", "state_sum")
    series = out.get(q)
    cid, kind, cf = spec["id"], spec["kind"], spec.get("closed_form")
    if series is None:
        return CheckResult(
            cid,
            kind,
            False,
            skipped=True,
            closed_form=cf,
            detail=f"implementation reported no '{q}' series",
        )
    vals = _column(series, spec.get("index"))
    if len(vals) < 2:
        return CheckResult(cid, kind, False, detail="need >= 2 samples", closed_form=cf)
    if not _finite(vals):
        return CheckResult(cid, kind, False, detail="non-finite values", closed_form=cf)
    need = float(spec.get("min_increase", 0.0))
    rise = vals[-1] - vals[0]
    worst = min(b - a for a, b in zip(vals, vals[1:]))
    ok = rise >= need and worst >= -abs(spec.get("abs_tol", 1e-9))
    return CheckResult(
        cid,
        kind,
        ok,
        measured=rise,
        tolerance=need,
        closed_form=cf,
        detail=(
            ""
            if ok
            else (
                f"{q} rose by {rise:.6g} over the run (required {need:.3g}), with a worst "
                f"step of {worst:.6g}. A system that merely fails to decrease is not "
                f"creating entropy."
            )
        ),
    )


CHECK_KINDS = {
    "strictly_increasing": _check_strictly_increasing,
    "monotone_non_increasing": _check_monotone_non_increasing,
    "final_value": _check_final_value,
    "relative_drift": _check_relative_drift,
    "non_negative": _check_non_negative,
    "lower_bound": _check_lower_bound,
    "matrix_skew_symmetric": _check_matrix_skew,
    "matrix_psd": _check_matrix_psd,
    "matrix_equals": _check_matrix_equals,
    "manifest_schema_valid": _check_manifest_schema_valid,
    "manifest_roundtrip": _check_manifest_roundtrip,
    "manifest_rejects_non_finite": _check_manifest_rejects_non_finite,
}


def run_check(spec: dict, outputs: dict) -> CheckResult:
    """Run one check from a fixture against an implementation's reported outputs.

    Args:
        spec: A single entry from a fixture's ``checks`` array.
        outputs: The ``outputs`` object the implementation reported.

    Returns:
        A :class:`CheckResult`. Unknown check kinds fail rather than skip — a
        fixture referring to a check this runner does not implement is a
        version mismatch, and passing silently would be worse than failing.
    """
    kind = spec.get("kind")
    fn = CHECK_KINDS.get(kind)
    if fn is None:
        return CheckResult(
            spec.get("id", "?"),
            str(kind),
            False,
            detail=f"unknown check kind {kind!r}; this runner implements "
            f"{sorted(CHECK_KINDS)}. The fixture may require a newer otwin-spec.",
        )
    try:
        return fn(spec, outputs)
    except Exception as exc:  # a malformed report must not crash the suite
        return CheckResult(
            spec.get("id", "?"),
            str(kind),
            False,
            detail=f"check raised {type(exc).__name__}: {exc}",
        )


def load_json(path: str) -> Any:
    """Read JSON, rejecting the non-standard NaN/Infinity tokens."""

    def _reject(constant: str) -> Any:
        raise ValueError(
            f"file contains the non-JSON constant {constant!r}. NaN and Infinity "
            f"are not valid JSON (RFC 8259) and cannot be read from Julia or MATLAB."
        )

    with open(path, encoding="utf-8") as fh:
        return json.load(fh, parse_constant=_reject)
