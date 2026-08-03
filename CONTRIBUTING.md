# Contributing to otwin-spec

Contributions are welcome, and this file tells you exactly what "done" looks
like so you are not guessing.

## What this repository needs right now

A new fixture: a physical system with a closed-form answer that no current fixture covers (thermal, electrical, chemical, mechanical). A fixture needs the system, the analytic result, a stated rationale, and a mutant that proves the check actually works. Adapters for new languages are equally welcome.

Issues labelled [`good-first-issue`](https://github.com/otwin-core/otwin-spec/labels/good-first-issue)
are scoped so that a first-time contributor can finish one in an evening.

## Practices

We follow [ColPrac](https://github.com/SciML/ColPrac), the Contributor's Guide
on Collaborative Practices for Community Packages. We have not written our own
version, on purpose — ColPrac is better than anything a single maintainer would
produce, and it is already familiar to people coming from the scientific Julia
and Python ecosystems.

Short form:

- Open an issue before a large change, so nobody wastes an evening.
- One logical change per pull request.
- Breaking changes need a major version bump and a note in `CHANGELOG.md`.
- Review is about the code, never the person.

## Standards enforced by CI

A pull request must pass all of these before it can be merged. None of them
are advisory, and CI does not swallow failures.

- `pytest` — all tests pass
- `ruff` and `black` — formatting and linting clean
- `mypy --strict` — types complete on the public surface
- coverage does not decrease
- every public symbol has a docstring
- conformance suite from [otwin-spec](https://github.com/otwin-core/otwin-spec) passes

## Development setup

```bash
git clone https://github.com/otwin-core/otwin-spec.git
cd otwin-spec
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## The one rule that matters

**Every quantitative claim must be reproducible from a seeded script.**

No hand-typed numbers in a README, no benchmark table without the script that
generated it, no "roughly 3x faster" without a command someone else can run.
If a number cannot be regenerated, it does not go in.

## Getting help

Open an issue. A question is a legitimate use of the issue tracker, and an
unclear docstring is a bug.
