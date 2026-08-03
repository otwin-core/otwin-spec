"""The conformance runner.

An implementation is a **subprocess**, not a library. The runner writes a
fixture to its stdin and reads a result document from its stdout. That is the
entire integration surface, and it is why the same suite can judge Python,
Julia and MATLAB without this package knowing anything about any of them.

The contract for an adapter
---------------------------

Input on stdin: one fixture document (see ``schemas/fixture-1.0.json``).

Output on stdout: one result document::

    {
      "fixture_id": "dc_motor_steady_state",
      "implementation": "julia",
      "version": "0.1.0",
      "outputs": {
        "t": [...],
        "state": [[...], ...],
        "energy": [...],
        "entropy_production": [...],
        "matrices": {"J": [[[...]]], "R": [[[...]]]},
        "manifest": {...},
        "manifest_roundtrip": {...},
        "rejects_non_finite": true
      },
      "unsupported": ["..."]
    }

An adapter reports **numbers only**; it never judges itself. Anything it cannot
produce it simply omits, and the corresponding checks are reported as skipped.
Listing a fixture id in ``unsupported`` skips it without counting as a failure
— honest partial conformance is the expected state of a young binding, and is
far more useful than a binding that pretends.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .checks import CheckResult, load_json, run_check

__all__ = [
    "FixtureResult",
    "ConformanceReport",
    "run_fixture",
    "run_suite",
    "fixture_dir",
    "as_task",
]


def fixture_dir() -> Path:
    """Directory holding the golden fixtures shipped with this package."""
    return Path(__file__).parent / "fixtures"


def load_fixtures(only: list[str] | None = None) -> list[dict]:
    """Load all shipped fixtures, optionally filtered by id."""
    out = []
    for p in sorted(fixture_dir().glob("*.json")):
        if p.name == "manifest_example.json":
            continue
        f = load_json(str(p))
        if only and f["id"] not in only:
            continue
        out.append(f)
    return out


@dataclass
class FixtureResult:
    """Outcome of one fixture against one implementation."""

    fixture_id: str
    title: str
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None
    unsupported: bool = False

    @property
    def passed(self) -> bool:
        """True only when at least one check ran and none failed.

        A fixture whose checks were *all* skipped does not pass. An adapter
        that reports no numbers has not demonstrated anything, and treating
        silence as conformance would let an empty implementation earn a green
        badge — the single worst failure mode for a suite like this.
        """
        if self.error or self.unsupported:
            return False
        ran = [c for c in self.checks if not c.skipped]
        return bool(ran) and all(c.passed for c in ran)

    @property
    def n_passed(self) -> int:
        return sum(1 for c in self.checks if c.passed and not c.skipped)

    @property
    def n_failed(self) -> int:
        return sum(1 for c in self.checks if not c.passed and not c.skipped)

    @property
    def n_skipped(self) -> int:
        return sum(1 for c in self.checks if c.skipped)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "title": self.title,
            "status": (
                "unsupported"
                if self.unsupported
                else "error" if self.error else "pass" if self.passed else "fail"
            ),
            "error": self.error,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class ConformanceReport:
    """The full result of running the suite against one implementation."""

    implementation: str
    adapter: str
    spec_version: str
    results: list[FixtureResult] = field(default_factory=list)

    @property
    def n_pass(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def n_fail(self) -> int:
        return sum(1 for r in self.results if not r.passed and not r.unsupported)

    @property
    def n_unsupported(self) -> int:
        return sum(1 for r in self.results if r.unsupported)

    @property
    def conformant(self) -> bool:
        """True when nothing failed.

        Deliberately tolerant of *declared* gaps and intolerant of silent ones:
        a fixture the adapter listed as unsupported does not block conformance,
        but a fixture it attempted and got wrong does.
        """
        return self.n_fail == 0 and self.n_pass > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "implementation": self.implementation,
            "adapter": self.adapter,
            "spec_version": self.spec_version,
            "conformant": self.conformant,
            "summary": {
                "passed": self.n_pass,
                "failed": self.n_fail,
                "unsupported": self.n_unsupported,
                "total": len(self.results),
            },
            "fixtures": [r.to_dict() for r in self.results],
        }

    def badge(self) -> str:
        """A shields.io endpoint payload, so a repo can display its status."""
        total = self.n_pass + self.n_fail
        colour = (
            "brightgreen"
            if self.conformant and self.n_unsupported == 0
            else "yellow" if self.conformant else "red"
        )
        return json.dumps(
            {
                "schemaVersion": 1,
                "label": "otwin conformance",
                "message": f"{self.n_pass}/{total}"
                + (f" (+{self.n_unsupported} n/a)" if self.n_unsupported else ""),
                "color": colour,
            }
        )


#: Fixture keys that carry the answers and MUST NOT reach an adapter.
#:
#: An adapter that can read ``checks[].expected`` can echo it back and pass
#: without containing any physics at all. The task document therefore carries
#: only what is needed to *run* the scenario: the model, its parameters, and
#: the scenario itself.
_ANSWER_KEYS = ("checks", "derived_quantities", "rationale")


def as_task(fixture: dict) -> dict:
    """Strip the answers from a fixture, leaving only what is needed to run it.

    This is the single most important function in the runner. Without it, a
    sixty-line adapter that reads the expected values out of its own input and
    echoes them back scores a perfect, bright-green result while containing no
    model, no integrator and no physics whatsoever.
    """
    return {k: v for k, v in fixture.items() if k not in _ANSWER_KEYS}


def run_fixture(fixture: dict, adapter: str, timeout: float = 120.0) -> FixtureResult:
    """Run one fixture through an adapter subprocess and judge the result."""
    fr = FixtureResult(fixture_id=fixture["id"], title=fixture.get("title", ""))
    try:
        proc = subprocess.run(
            shlex.split(adapter),
            input=json.dumps(as_task(fixture)),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        fr.error = f"adapter timed out after {timeout:.0f}s"
        return fr
    except FileNotFoundError:
        fr.error = f"adapter not found: {adapter!r}"
        return fr

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        fr.error = f"adapter exited {proc.returncode}: " + " | ".join(tail)
        return fr

    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        head = (proc.stdout or "")[:200].replace("\n", " ")
        fr.error = f"adapter stdout was not JSON ({exc}); first bytes: {head!r}"
        return fr

    if fixture["id"] in (report.get("unsupported") or []):
        fr.unsupported = True
        return fr

    outputs = report.get("outputs") or {}
    for spec in fixture.get("checks", []):
        fr.checks.append(run_check(spec, outputs))
    return fr


def run_suite(
    adapter: str,
    implementation: str = "unknown",
    only: list[str] | None = None,
    timeout: float = 120.0,
) -> ConformanceReport:
    """Run every shipped fixture against an adapter."""
    from . import __version__

    rep = ConformanceReport(
        implementation=implementation, adapter=adapter, spec_version=__version__
    )
    for fx in load_fixtures(only=only):
        rep.results.append(run_fixture(fx, adapter, timeout=timeout))
    return rep


def format_report(rep: ConformanceReport, verbose: bool = False) -> str:
    """Render a report for a terminal."""
    lines = [
        "",
        f"  otwin conformance suite v{rep.spec_version}",
        f"  implementation: {rep.implementation}",
        f"  adapter:        {rep.adapter}",
        "",
    ]
    width = max((len(r.fixture_id) for r in rep.results), default=10) + 2
    for r in rep.results:
        if r.unsupported:
            mark, note = "  n/a ", "declared unsupported"
        elif r.error:
            mark, note = " ERROR", r.error
        elif r.passed:
            mark = "  PASS"
            note = f"{r.n_passed} checks" + (f", {r.n_skipped} skipped" if r.n_skipped else "")
        else:
            mark = "  FAIL"
            note = f"{r.n_failed} of {r.n_passed + r.n_failed} checks failed"
        lines.append(f"  {mark}  {r.fixture_id:<{width}} {note}")
        for c in r.checks:
            if (not c.passed and not c.skipped) or (verbose and not c.skipped):
                status = "fail" if not c.passed else "ok"
                lines.append(f"          [{status}] {c.check_id}")
                if c.closed_form:
                    lines.append(f"                 expected: {c.closed_form}")
                if c.detail:
                    lines.append(f"                 {c.detail}")
            elif c.skipped and verbose:
                lines.append(f"          [skip] {c.check_id}: {c.detail}")
    lines += [
        "",
        f"  {rep.n_pass} passed, {rep.n_fail} failed, {rep.n_unsupported} unsupported",
        f"  conformant: {'yes' if rep.conformant else 'NO'}",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``otwin-conformance``."""
    import argparse

    ap = argparse.ArgumentParser(
        prog="otwin-conformance",
        description=(
            "Run the Otwin conformance suite against an implementation. The "
            "implementation is a subprocess that reads a fixture on stdin and "
            "writes a result document on stdout."
        ),
    )
    ap.add_argument(
        "adapter",
        nargs="?",
        help="Command to run the adapter, e.g. 'python -m otwin_spec.adapters.python' "
        "or 'julia --project=. adapters/conformance.jl'. The shorthand "
        "'python' selects the reference adapter.",
    )
    ap.add_argument("--name", default=None, help="Implementation name for the report")
    ap.add_argument("--only", nargs="*", default=None, help="Run only these fixture ids")
    ap.add_argument("--report", default=None, help="Write the JSON report to this path")
    ap.add_argument("--badge", default=None, help="Write a shields.io badge JSON here")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--list", action="store_true", help="List fixtures and exit")
    a = ap.parse_args(argv)

    if a.list:
        for f in load_fixtures():
            print(f"{f['id']:<34} {f.get('title', '')}")
        return 0
    if not a.adapter:
        ap.error("an adapter is required unless --list is given")

    adapter = a.adapter
    name = a.name
    if adapter == "python":
        adapter = f"{sys.executable} -m otwin_spec.adapters.reference"
        name = name or "python (reference)"

    rep = run_suite(adapter, implementation=name or adapter, only=a.only, timeout=a.timeout)
    print(format_report(rep, verbose=a.verbose))
    if a.report:
        Path(a.report).write_text(json.dumps(rep.to_dict(), indent=2), encoding="utf-8")
        print(f"  report written to {a.report}\n")
    if a.badge:
        Path(a.badge).write_text(rep.badge(), encoding="utf-8")
    return 0 if rep.conformant else 1


if __name__ == "__main__":
    raise SystemExit(main())
