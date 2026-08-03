"""Deliberately broken adapters, used to prove the suite has teeth.

A conformance suite that only ever passes is decoration. These mutants each
introduce one physically meaningful defect — the kind a real implementation
actually ships — and the test suite asserts that the corresponding fixture
fails. If a mutant ever passes, the check protecting against it is broken.
"""

from __future__ import annotations

import json
import sys

import numpy as np

from otwin_spec import reference
from otwin_spec.adapters import reference as adapter

MUTATION = sys.argv[1] if len(sys.argv) > 1 else "none"


def _patch() -> None:
    if MUTATION == "non_skew_J":
        # A gyrator coupling that is not skew-symmetric: the interconnection
        # is no longer lossless, so the power balance silently stops holding.
        orig = reference.dc_motor

        def broken(**kw):
            m = orig(**kw)
            m.J = lambda x: np.array([[0.0, -0.5], [0.4, 0.0]])
            return m

        reference.MODELS["dc_motor"] = broken

    elif MUTATION == "negative_R":
        # Negative dissipation: the model creates energy instead of losing it.
        # Deliberately small in magnitude. A large negative R makes the run
        # diverge, which the runner reports as an adapter error — caught, but
        # for the wrong reason. The interesting failure is the one that stays
        # finite and plausible, and is caught by the physics rather than by an
        # overflow.
        orig = reference.water_tank

        def broken(**kw):
            m = orig(**kw)
            m.R = lambda x: np.array([[-1.0e-6]])
            return m

        reference.MODELS["water_tank"] = broken

    elif MUTATION == "energy_creating_integrator":
        # A plausible-looking but wrong stepper that adds a little energy each
        # step. Accuracy on a short horizon looks fine; the long forecast drifts.
        def broken_sim(model, x0, t, u):
            # A non-symplectic stepper that leaks a little energy IN each step.
            # Short-horizon accuracy looks fine; the long forecast drifts upward
            # once the true energy has decayed below the leak. This is the
            # classic failure the structure-preserving requirement exists for.
            X, e = reference.simulate(model, x0, t, u)
            ramp = 0.02 * abs(e[0]) * np.arange(len(e)) / max(len(e) - 1, 1)
            return X, e + ramp

        adapter.simulate = broken_sim

    elif MUTATION == "wrong_steady_state":
        # The gyrator constant is off by 10%: the twin converges confidently
        # to the wrong answer.
        orig = reference.dc_motor
        reference.MODELS["dc_motor"] = lambda **kw: orig(**{**kw, "K": kw.get("K", 0.5) * 1.1})

    elif MUTATION == "second_law_violation":
        orig = reference.heat_exchanger_2body

        def broken(**kw):
            m = orig(**kw)
            m.entropy_production = lambda x, u=None: -1.0
            return m

        reference.MODELS["heat_exchanger_2body"] = broken

    elif MUTATION == "nan_manifest":
        # Writes NaN into the manifest: silently unreadable from Julia/MATLAB.
        orig = adapter._manifest_outputs

        def broken(fixture):
            out = orig(fixture)
            out["rejects_non_finite"] = False
            return out

        adapter._manifest_outputs = broken

    elif MUTATION == "diverged":

        def broken_sim(model, x0, t, u):
            X, e = reference.simulate(model, x0, t, u)
            e = e.copy()
            e[len(e) // 2 :] = np.nan
            return X, e

        adapter.simulate = broken_sim


def main() -> int:
    if MUTATION == "fabricator":
        return fabricator_main()
    _patch()
    fixture = json.load(sys.stdin)
    report = {
        "fixture_id": fixture.get("id"),
        "implementation": f"mutant:{MUTATION}",
        "version": "0",
        "unsupported": [],
    }
    try:
        report["outputs"] = adapter._sanitise(adapter.run(fixture))
    except Exception as exc:
        report["outputs"] = {}
        report["note"] = str(exc)
    json.dump(report, sys.stdout, allow_nan=False)
    return 0


# ==========================================================================
# The fabricator: an "implementation" containing no physics whatsoever.
#
# This is the most important adversary in the suite, and the one a
# conformance suite usually fails to survive. Every other mutant is an honest
# implementation with one thing broken. This one is not trying at all: it
# looks at whatever it is given, emits plausibly-shaped numbers, and hopes.
#
# It exists to pin the property that fixtures MUST NOT ship their answers to
# the adapter. An earlier version of the runner sent each adapter the whole
# fixture, including `checks[].expected`, `bound`, `value` and `max_drift`.
# Sixty lines like these then scored 7/7, bright green, exit 0 — with no
# model, no integrator and no physics of any kind. `runner.as_task()` now
# strips the answers, and this test asserts that it keeps doing so.
# ==========================================================================


def fabricate(task: dict) -> dict:
    """Emit plausible-looking numbers, using anything the task leaks."""
    out: dict = {}
    n = 64

    # Whatever the task happens to reveal about expected answers.
    leaked = json.dumps(task)
    has_answers = any(k in leaked for k in ("expected", "max_drift", '"bound"', "closed_form"))

    sc = task.get("scenario", {})
    ns = len(sc.get("x0") or (sc.get("sample_states") or [[0.0]])[0])

    if "t" in sc:
        t = sc["t"]
        n = int(t.get("num", 64))
        out["t"] = list(np.linspace(t["start"], t["stop"], n))

    # A monotonically decaying energy trace satisfies passivity checks without
    # any dynamics behind it at all.
    out["energy"] = list(np.exp(-np.linspace(0, 3, n)))
    out["state"] = [[0.0] * ns for _ in range(n)]
    out["state_sum"] = list(np.linspace(0.0, 1.0, n))
    out["entropy_production"] = [0.5] * n
    # Zero matrices are skew AND positive semidefinite. Both checks pass.
    out["matrices"] = {
        "J": [[[0.0] * ns for _ in range(ns)]],
        "R": [[[0.0] * ns for _ in range(ns)]],
    }
    out["_saw_answers"] = has_answers

    # If the runner ever leaks the answer key again, read it straight back.
    for chk in task.get("checks", []):
        if "expected" in chk:
            q, i = chk.get("quantity", "state"), chk.get("index")
            if q == "energy":
                out["energy"] = list(np.linspace(1.0, chk["expected"], n))
            elif q == "state" and i is not None:
                for row in out["state"]:
                    row[i] = chk["expected"]
    return out


def fabricator_main() -> int:
    task = json.load(sys.stdin)
    json.dump(
        {
            "fixture_id": task.get("id"),
            "implementation": "FABRICATOR (no physics)",
            "version": "0",
            "unsupported": [],
            "outputs": fabricate(task),
        },
        sys.stdout,
        allow_nan=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
