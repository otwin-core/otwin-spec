"""Schema loading and validation.

The schemas are the normative documents. This module is the convenience
wrapper that reads them; the JSON files themselves are what Julia and MATLAB
consume.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = ["schema_dir", "load_schema", "validate_manifest"]


def schema_dir() -> Path:
    """Directory holding the normative JSON Schema documents."""
    return Path(__file__).parent / "schemas"


@lru_cache(maxsize=8)
def load_schema(name: str = "twin-manifest-1.0") -> dict[str, Any]:
    """Load a schema by name (without the .json suffix)."""
    return json.loads((schema_dir() / f"{name}.json").read_text(encoding="utf-8"))


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Validate a Twin Manifest. Returns a list of human-readable errors.

    Uses ``jsonschema`` when available and falls back to a hand-written subset
    otherwise, so the suite still runs in a minimal environment. The fallback
    checks the rules that actually break cross-language interoperability.
    """
    try:
        import jsonschema
    except ImportError:
        return _fallback_validate(manifest)

    validator = jsonschema.Draft202012Validator(load_schema())
    errors = []
    for e in sorted(validator.iter_errors(manifest), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in e.path) or "(root)"
        errors.append(f"{loc}: {e.message}")
    errors.extend(_semantic_checks(manifest))
    return errors


def _fallback_validate(m: dict[str, Any]) -> list[str]:
    errors = []
    for key in ("name", "model_class", "model_kind", "n_states", "n_inputs", "provenance"):
        if key not in m:
            errors.append(f"(root): missing required field {key!r}")
    valid = {
        "port_hamiltonian",
        "irreversible_phs",
        "empirical_law",
        "learned_phs",
        "composite",
    }
    if m.get("model_class") not in valid:
        errors.append(f"model_class: {m.get('model_class')!r} is not one of {sorted(valid)}")
    if not isinstance(m.get("n_states"), int) or m.get("n_states", 0) < 1:
        errors.append("n_states: must be an integer >= 1")
    prov = m.get("provenance")
    if isinstance(prov, dict):
        created = prov.get("created", "")
        if not (isinstance(created, str) and created.endswith("Z") and "." not in created):
            errors.append(
                "provenance/created: must be UTC with a Z suffix and no fractional "
                "seconds, so Julia and MATLAB can parse it without extra packages"
            )
    errors.extend(_semantic_checks(m))
    return errors


def _semantic_checks(m: dict[str, Any]) -> list[str]:
    """Rules a JSON Schema cannot express."""
    errors = []
    est = m.get("estimated") or []
    if isinstance(est, str):
        errors.append("estimated: must be an array of names, not a single string")
    else:
        unknown = set(est) - set(m.get("parameters") or {})
        if unknown:
            errors.append(f"estimated: names not present in parameters: {sorted(unknown)}")
    v = m.get("validation")
    # `isinstance(..., bool)`, not `not in (True, False)`. In Python `1 == True`,
    # so `1 in (True, False)` is True and the integer form -- the single most
    # likely round-trip artefact, since MATLAB's jsonencode writes logicals as
    # 1/0 -- sailed straight through the check written to catch it.
    if isinstance(v, dict) and "leakage_free" in v and not isinstance(v["leakage_free"], bool):
        errors.append(
            "validation/leakage_free: must be a JSON boolean. A 1, a 0 or the "
            "string 'false' is a round-trip artefact and must not read as validated."
        )
    return errors
