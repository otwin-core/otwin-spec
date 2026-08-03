"""Tests for the conformance suite itself.

The most important tests here are the *mutant* tests. A conformance suite that
only ever passes is decoration; these assert that each deliberately broken
implementation is caught by the check that exists to catch it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from otwin_spec import fixture_dir, load_fixtures, run_suite, validate_manifest

MUTANTS = Path(__file__).parent / "mutants.py"
REF = f"{sys.executable} -m otwin_spec.adapters.reference"


def mutant(name: str) -> str:
    return f"{sys.executable} {MUTANTS} {name}"


# --------------------------------------------------------------------------
# The reference implementation must pass everything
# --------------------------------------------------------------------------


def test_reference_implementation_is_conformant():
    rep = run_suite(REF, implementation="python (reference)")
    assert rep.conformant, rep.to_dict()
    assert rep.n_fail == 0
    assert rep.n_pass == len(load_fixtures())


def test_every_fixture_has_at_least_one_check():
    for f in load_fixtures():
        assert f.get("checks"), f"fixture {f['id']} has no checks"


def test_every_fixture_declares_a_rationale():
    """A fixture without a stated reason cannot be argued with, or improved."""
    for f in load_fixtures():
        assert f.get("rationale"), f"fixture {f['id']} has no rationale"
        assert len(f["rationale"]) > 40


def test_every_check_names_its_closed_form_or_is_structural():
    structural = {"manifest_schema_valid", "manifest_roundtrip"}
    for f in load_fixtures():
        for c in f["checks"]:
            if c["kind"] not in structural:
                assert c.get("closed_form"), (
                    f"{f['id']}/{c['id']} states no closed form, so a failure "
                    f"report cannot explain what was expected"
                )


# --------------------------------------------------------------------------
# Mutants: each defect must be caught by the check meant to catch it
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation,fixture,expect_check",
    [
        ("non_skew_J", "dc_motor_steady_state", "J_skew"),
        ("negative_R", "phs_structure_water_tank", "R_psd"),
        ("negative_R", "water_tank_passivity", "energy_non_increasing"),
        ("energy_creating_integrator", "water_tank_passivity", "energy_non_increasing"),
        (
            "energy_creating_integrator",
            "dc_motor_coastdown_passivity",
            "energy_non_increasing",
        ),
        ("wrong_steady_state", "dc_motor_steady_state", "p_steady_state"),
        ("second_law_violation", "iphs_second_law", "entropy_production_non_negative"),
        ("nan_manifest", "manifest_roundtrip", "rejects_nan"),
        ("diverged", "water_tank_passivity", "energy_non_increasing"),
    ],
)
def test_mutant_is_caught(mutation, fixture, expect_check):
    rep = run_suite(mutant(mutation), implementation=f"mutant:{mutation}", only=[fixture])
    assert not rep.conformant, f"mutant {mutation!r} was NOT caught by {fixture}"
    result = rep.results[0]
    failed = {c.check_id for c in result.checks if not c.passed and not c.skipped}
    assert expect_check in failed, (
        f"{fixture} failed, but not via {expect_check!r}; failures were {sorted(failed)}. "
        f"The suite caught the mutant for the wrong reason."
    )


def test_a_failure_report_explains_itself():
    """A failure must say what was expected and by how much it missed."""
    rep = run_suite(mutant("non_skew_J"), only=["dc_motor_steady_state"])
    bad = [c for c in rep.results[0].checks if c.check_id == "J_skew"][0]
    assert bad.detail and "skew" in bad.detail.lower()
    assert bad.closed_form
    assert bad.measured is not None and bad.measured > 0


def test_unmutated_control_passes():
    """Guards against the mutant harness itself breaking everything."""
    rep = run_suite(mutant("none"))
    assert rep.conformant


# --------------------------------------------------------------------------
# Adapter contract
# --------------------------------------------------------------------------


def test_missing_adapter_is_an_error_not_a_pass():
    rep = run_suite("this-command-does-not-exist-9f3a", only=["water_tank_passivity"])
    assert not rep.conformant
    assert "not found" in (rep.results[0].error or "")


def test_non_json_stdout_is_an_error_not_a_pass():
    rep = run_suite(f"{sys.executable} -c \"print('hello')\"", only=["water_tank_passivity"])
    assert not rep.conformant
    assert "not JSON" in (rep.results[0].error or "")


def test_crashing_adapter_is_an_error_not_a_pass():
    rep = run_suite(f'{sys.executable} -c "raise SystemExit(3)"', only=["iphs_second_law"])
    assert not rep.conformant
    assert "exited 3" in (rep.results[0].error or "")


def test_declared_unsupported_does_not_block_conformance():
    """A young binding may honestly declare gaps without being marked wrong."""
    script = (
        "import json,sys; f=json.load(sys.stdin); "
        "json.dump({'unsupported':[f['id']],'outputs':{}}, sys.stdout)"
    )
    rep = run_suite(f'{sys.executable} -c "{script}"')
    assert rep.n_unsupported == len(load_fixtures())
    assert rep.n_fail == 0
    assert not rep.conformant  # nothing passed, so it is not yet conformant either


def test_silence_is_not_conformance():
    """An adapter that reports nothing must skip, and skipping is not passing."""
    script = "import json,sys; json.load(sys.stdin); json.dump({'outputs':{}}, sys.stdout)"
    rep = run_suite(f'{sys.executable} -c "{script}"', only=["water_tank_passivity"])
    assert not rep.conformant
    assert rep.results[0].n_skipped > 0


def test_unknown_check_kind_fails_rather_than_passing_silently():
    from otwin_spec import run_check

    r = run_check({"id": "x", "kind": "invented_in_the_future"}, {})
    assert not r.passed
    assert "unknown check kind" in r.detail


# --------------------------------------------------------------------------
# Manifest schema
# --------------------------------------------------------------------------


def _example():
    return json.loads((fixture_dir() / "manifest_example.json").read_text())


def test_example_manifest_validates():
    assert validate_manifest(_example()) == []


@pytest.mark.parametrize(
    "mutate,expect",
    [
        (lambda m: m.pop("name"), "name"),
        (lambda m: m.update(model_class="neural_vibes"), "model_class"),
        (lambda m: m.update(n_states=0), "n_states"),
        (lambda m: m.update(estimated=["not_a_parameter"]), "estimated"),
        (lambda m: m["validation"].update(leakage_free=1), "leakage_free"),
        (lambda m: m["validation"].update(leakage_free="false"), "leakage_free"),
        (
            lambda m: m["provenance"].update(created="2026-08-03T00:00:00.123456+00:00"),
            "created",
        ),
    ],
)
def test_schema_rejects_a_broken_manifest(mutate, expect):
    m = _example()
    mutate(m)
    errors = validate_manifest(m)
    assert errors, f"schema accepted a manifest that should fail on {expect}"
    assert any(expect in e for e in errors), f"errors did not mention {expect}: {errors}"


def test_schema_accepts_unknown_forward_compatible_fields():
    m = _example()
    m["invented_by_a_future_version"] = {"x": 1}
    assert validate_manifest(m) == []


def test_badge_payload_is_valid_shields_io():
    rep = run_suite(REF)
    b = json.loads(rep.badge())
    assert b["schemaVersion"] == 1
    assert b["color"] in {"brightgreen", "yellow", "red"}


def test_cli_runs_and_exits_zero_for_the_reference():
    r = subprocess.run(
        [sys.executable, "-m", "otwin_spec.runner", "python"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "conformant: yes" in r.stdout


def test_cli_exits_nonzero_for_a_mutant():
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "otwin_spec.runner",
            mutant("negative_R"),
            "--only",
            "phs_structure_water_tank",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    assert "conformant: NO" in r.stdout


# --------------------------------------------------------------------------
# The adversary that is not trying
# --------------------------------------------------------------------------


def test_an_adapter_with_no_physics_is_not_conformant():
    """The single most important test in this repository.

    Every other mutant is an honest implementation with one defect. This one
    contains no model, no integrator and no physics at all — it emits
    plausibly-shaped numbers and hopes. If fixtures ever ship their answers to
    the adapter again, it will score a perfect green result, and the entire
    suite will be decoration.
    """
    rep = run_suite(mutant("fabricator"), implementation="FABRICATOR")
    assert not rep.conformant, (
        "an adapter containing no physics passed the conformance suite. "
        "Check that runner.as_task() is still stripping the answer key."
    )
    assert rep.n_fail >= 4, f"only {rep.n_fail} fixtures caught the fabricator"


def test_the_task_document_carries_no_answers():
    """Adapters must receive the question, never the answer key."""
    from otwin_spec.runner import as_task

    for f in load_fixtures():
        task = as_task(f)
        leaked = json.dumps(task)
        for forbidden in (
            "expected",
            "max_drift",
            "closed_form",
            "rel_tol",
            "abs_tol",
            "min_increase",
            "rationale",
        ):
            assert (
                forbidden not in leaked
            ), f"fixture {f['id']} leaks {forbidden!r} to the adapter"
        # but it must still carry everything needed to RUN the scenario
        assert "model_kind" in task and "scenario" in task and "parameters" in task


def test_fabricator_confirms_it_saw_no_answers():
    """End-to-end proof that the stripping actually happened in transit."""
    import subprocess

    fixture = [f for f in load_fixtures() if f["id"] == "dc_motor_steady_state"][0]
    from otwin_spec.runner import as_task

    proc = subprocess.run(
        mutant("fabricator").split(),
        input=json.dumps(as_task(fixture)),
        capture_output=True,
        text=True,
    )
    assert json.loads(proc.stdout)["outputs"]["_saw_answers"] is False
