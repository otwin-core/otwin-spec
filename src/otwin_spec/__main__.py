"""Allow `python -m otwin_spec` as an alias for the conformance CLI."""

from .runner import main

if __name__ == "__main__":
    raise SystemExit(main())
