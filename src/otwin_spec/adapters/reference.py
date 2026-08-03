"""The reference adapter.

Reads a fixture on stdin, runs it against the reference models, writes a
result document on stdout. It is both the proof that the suite works and the
worked example every other language adapter is written from.

An adapter's whole job is to *report numbers*. It never decides whether they
are right — see :mod:`otwin_spec.checks` for why that separation matters.

Run it directly::

    echo '<fixture json>' | python -m otwin_spec.adapters.reference
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any

import numpy as np

from ..reference import build, simulate


def _time_grid(spec: dict) -> np.ndarray:
    t = spec["t"]
    return np.linspace(float(t["start"]), float(t["stop"]), int(t["num"]))


def _inputs(spec: dict, n: int, m: int) -> np.ndarray:
    u = spec.get("u", {"kind": "zeros"})
    kind = u.get("kind", "zeros")
    if kind == "zeros":
        return np.zeros((n, m))
    if kind == "constant":
        return np.tile(np.atleast_1d(np.asarray(u["value"], dtype=float)), (n, 1))
    raise ValueError(f"unsupported input kind {kind!r}")


def _manifest_outputs(fixture: dict) -> dict[str, Any]:
    """Exercise the manifest path: schema, round-trip, and NaN rejection."""
    from ..runner import fixture_dir

    example = json.loads(
        (fixture_dir() / fixture["scenario"]["manifest_fixture"]).read_text(encoding="utf-8")
    )
    # Round-trip through a strict JSON writer, exactly as a binding would.
    text = json.dumps(example, allow_nan=False)
    roundtrip = json.loads(text)

    # Does the implementation refuse to serialise a non-finite parameter?
    poisoned = json.loads(text)
    poisoned["parameters"]["c"] = float("nan")
    try:
        json.dumps(poisoned, allow_nan=False)
        rejects = False
    except ValueError:
        rejects = True

    return {
        "manifest": example,
        "manifest_roundtrip": roundtrip,
        "rejects_non_finite": rejects,
    }


def run(fixture: dict) -> dict[str, Any]:
    """Produce the outputs a fixture's checks need."""
    scenario = fixture.get("scenario", {})
    if "manifest_fixture" in scenario:
        return _manifest_outputs(fixture)

    model = build(fixture["model_kind"], dict(fixture.get("parameters", {})))
    out: dict[str, Any] = {}

    if "sample_states" in scenario:
        states = [np.asarray(s, dtype=float) for s in scenario["sample_states"]]
        out["matrices"] = {
            "J": [model.J(x).tolist() for x in states],
            "R": [model.R(x).tolist() for x in states],
        }
        out["state"] = [x.tolist() for x in states]
        out["energy"] = [model.H(x) for x in states]
        if model.entropy_production is not None:
            u0 = np.zeros(model.n_inputs)
            out["entropy_production"] = [model.entropy_production(x, u0) for x in states]

    if "x0" in scenario:
        t = _time_grid(scenario)
        u = _inputs(scenario, len(t), model.n_inputs)
        x0 = np.asarray(scenario["x0"], dtype=float)
        X, energy = simulate(model, x0, t, u)
        out["t"] = t.tolist()
        out["state"] = X.tolist()
        out["energy"] = energy.tolist()
        out["state_sum"] = X.sum(axis=1).tolist()
        out.setdefault("matrices", {})
        out["matrices"].setdefault("J", [model.J(X[0]).tolist()])
        out["matrices"].setdefault("R", [model.R(X[0]).tolist()])
        if model.entropy_production is not None:
            out["entropy_production"] = [
                model.entropy_production(X[i], u[i]) for i in range(len(t))
            ]
    return out


def _sanitise(o: Any) -> Any:
    """Replace non-finite floats with None so the report is valid JSON.

    An adapter must never emit bare NaN or Infinity: those are not JSON, and
    the runner would reject the whole report rather than the one check that
    diverged. Reporting ``null`` lets the relevant check fail precisely.
    """
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _sanitise(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_sanitise(v) for v in o]
    return o


def main() -> int:
    from .. import __version__

    fixture = json.load(sys.stdin)
    report: dict[str, Any] = {
        "fixture_id": fixture.get("id"),
        "implementation": "python (reference)",
        "version": __version__,
        "unsupported": [],
    }
    try:
        report["outputs"] = _sanitise(run(fixture))
    except KeyError as exc:
        report["outputs"] = {}
        report["unsupported"] = [fixture.get("id")]
        report["note"] = f"model not implemented: {exc}"
    json.dump(report, sys.stdout, allow_nan=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
