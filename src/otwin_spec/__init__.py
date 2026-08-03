"""otwin-spec — the normative Otwin specification and its conformance suite.

This package answers one question: **does this implementation actually do what
Otwin says a digital twin does?**

It contains no models and no solvers. It contains the JSON Schema for the Twin
Manifest, a set of golden fixtures whose answers are known analytically, and a
runner that judges any implementation in any language.

The fixtures are not synthetic. Each one is a physical system whose correct
behaviour follows from a closed-form result — a DC motor's steady state, a
pumped-hydro store's round-trip efficiency, the passivity of a draining tank.
An implementation either reproduces them or it does not.

Usage::

    otwin-conformance python                  # the reference implementation
    otwin-conformance "julia --project=. adapters/conformance.jl" --name julia
    otwin-conformance "matlab -batch otwin_conformance" --name matlab
"""

from .checks import CheckResult, run_check
from .runner import (
    ConformanceReport,
    FixtureResult,
    fixture_dir,
    format_report,
    load_fixtures,
    run_fixture,
    run_suite,
)
from .schema import load_schema, schema_dir, validate_manifest

__version__ = "0.1.0"
SPEC_VERSION = "1.0"

__all__ = [
    "__version__",
    "SPEC_VERSION",
    "run_suite",
    "run_fixture",
    "run_check",
    "load_fixtures",
    "fixture_dir",
    "format_report",
    "ConformanceReport",
    "FixtureResult",
    "CheckResult",
    "validate_manifest",
    "load_schema",
    "schema_dir",
]
