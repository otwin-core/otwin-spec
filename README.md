<div align="center">

<img src="https://raw.githubusercontent.com/otwin-core/otwin/main/assets/otwin_wm.png" width="35%">

# The normative Otwin specification, and a conformance suite that can judge any implementation in any language

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-brightgreen?style=flat-square)](https://opensource.org/license/apache-2-0)

</div>

## What this is

Otwin is Python-first. This package is what turns "physics-informed" from a claim into a property that something checks.

```bash
pip install otwin-spec
otwin-conformance python
```

```
  otwin conformance suite v0.1.0
  implementation: python (reference)

    PASS  dc_motor_coastdown_passivity   2 checks
    PASS  dc_motor_steady_state          3 checks
    PASS  iphs_second_law                3 checks
    PASS  manifest_roundtrip             3 checks
    PASS  phs_structure_water_tank       2 checks
    PASS  pumped_hydro_conservation      3 checks
    PASS  water_tank_drain_law           2 checks
    PASS  water_tank_passivity           2 checks

  8 passed, 0 failed, 0 unsupported
  conformant: yes
```

<br>

## Why bother

A model that declares port-Hamiltonian structure is making a **falsifiable claim**: that `J` is skew-symmetric, that `R` is positive semidefinite, and therefore that its forecasts cannot create energy at any horizon.

That claim is exactly what makes Otwin worth using instead of a neural network. It is also invisible on a test set — a model with a subtly wrong `J` scores beautifully on held-out data and then drifts when you extrapolate, which is precisely the situation the structure was supposed to protect you from.

So the claim needs a test. Here is what one looks like when it fails:

```
    FAIL  dc_motor_steady_state   3 of 3 checks failed
          [fail] J_skew
                 expected: the gyrator coupling is skew-symmetric
                 max |J + J^T| = 0.1 > 1e-12. J is not skew-symmetric, so the
                 interconnection is not lossless and the power balance does not hold.
```

---

## The fixtures are not synthetic

Every fixture is a physical system whose correct answer is known in closed form. Nothing is fitted; nothing is compared against a previous run of the same code.

| Fixture | Ground truth |
|---|---|
| `phs_structure_water_tank` | `J + Jᵀ = 0` and `λ_min(R) ≥ 0` — algebraic identities |
| `water_tank_passivity` | `dH/dt ≤ 0` with the inflow off, run past the emptying time |
| `water_tank_drain_law` | `h(t) = (√h₀ − c_d·a·√(2g)·t/2A)²` — exact Torricelli discharge |
| `dc_motor_steady_state` | `ω_ss = VK/(R_e·b + K²)`, `I_ss = Vb/(R_e·b + K²)` |
| `dc_motor_coastdown_passivity` | two stores coupled by a gyrator, energy non-increasing |
| `pumped_hydro_conservation` | `dH/dt = −c(p_u−p_l)²` — the analytic penstock leakage |
| `iphs_second_law` | `dU/dt = 0` (first law) **and** `σ = λ(T₁−T₂)²/(T₁T₂) ≥ 0` rising (second law) |
| `manifest_roundtrip` | schema validity, lossless round-trip, `NaN` rejection |

The DC motor structure is van der Schaft & Jeltsema (2014), Example 2.5. The irreversible system follows Ramírez, Maschke & Sbarbaro (2013).

<br>

## The suite has teeth, and proves it

A conformance suite that only ever passes is decoration. This one ships **mutants** — deliberately broken implementations, each with one realistic defect — and tests that assert each is caught *by the check meant to catch it*, not merely caught somehow.

| Mutant | Caught by | Sensitivity |
|---|---|---|
| `J` not skew-symmetric | `J_skew` | `\|J + Jᵀ\| > 10⁻¹²` |
| `R` negative | `R_psd`, and passivity downstream | `λ_min < −10⁻¹²` |
| energy-leaking integrator | `energy_non_increasing` | any step-to-step gain above `10⁻⁹` J |
| gyrator constant off by 10 % | `phi_steady_state`, `p_steady_state` | detected down to **0.001 %** |
| negative entropy production | `entropy_production_non_negative` | `σ < −10⁻¹²` |
| manifest writer emitting `NaN` | `rejects_nan` | any occurrence |
| **an adapter with no physics at all** | 7 of 8 fixtures | see below |
| diverged run | `energy_non_increasing` | refuses to answer on non-finite data |

### The adversary that is not trying

Every mutant above is an honest implementation with one thing broken. The one that actually threatens a suite like this is an adapter that **is not trying at all** — one that reads its input, emits plausibly-shaped numbers, and hopes.

An earlier version of this runner sent each adapter the whole fixture, including `checks[].expected`. Sixty lines of fabrication then scored **8/8, bright green, exit 0**, containing no model, no integrator and no physics whatsoever.

`runner.as_task()` now strips `checks`, `rationale` and `derived_quantities` before the document reaches the adapter: it receives the question, never the answer key. `tests/mutants.py fabricator` is that adapter, kept permanently, and `test_an_adapter_with_no_physics_is_not_conformant` asserts it stays caught.

It is still caught by only 7 of 8 fixtures. `phs_structure_water_tank` passes, because zero matrices are both skew-symmetric and positive semidefinite. That is a real and acknowledged limit: the matrix checks validate *a reported matrix*, never the model that produced the trajectory, and four sampled states prove nothing about the rest of the state space. Closing it properly needs cross-consistency checks — verifying that the reported `energy` equals `H(reported state)`, and that `ẋ ≈ (J−R)∇H + gu`. That is open work, and it is listed as such rather than hidden.

Two further properties of the runner deserve naming, because both are ways a suite like this usually rots:

- **Silence is not conformance.** An adapter that reports no numbers gets every check skipped — and a fixture whose checks all skipped does **not** pass. An empty implementation cannot earn a green badge.
- **Declared gaps are honest; silent ones are not.** A binding may list a fixture in `unsupported` and remain conformant-so-far. A binding that attempts a fixture and gets it wrong fails.

<br>

## Writing an adapter for a new language

An implementation is a **subprocess**, not a library. It reads a fixture on stdin and writes numbers on stdout. That is the entire integration surface — which is why this package knows nothing about Julia or MATLAB and can still judge them.

```
stdin  →  { "id": "dc_motor_steady_state", "model_kind": "dc_motor",
            "parameters": {...}, "scenario": {...} }
            # note: no "checks" — the adapter gets the question, not the answers

stdout ←  { "fixture_id": "dc_motor_steady_state",
            "implementation": "julia",
            "outputs": { "t": [...], "state": [[...]], "energy": [...],
                         "matrices": {"J": [[[...]]], "R": [[[...]]]} },
            "unsupported": [] }
```

**An adapter reports numbers. It never judges itself.** If the MATLAB binding checked its own passivity in MATLAB, a bug in the check would hide a bug in the model. Here, MATLAB reports an energy trace and this package decides whether it is monotone — the same code path that judges Python.

Omit anything you cannot produce; those checks are reported as skipped. List a fixture id in `unsupported` to declare it out of scope.

The reference adapter (`src/otwin_spec/adapters/reference.py`, ~130 lines) is the worked example. Adapter templates for Julia and MATLAB are in [`adapters/`](adapters).

```bash
otwin-conformance "julia --project=. adapters/conformance.jl" --name julia
otwin-conformance "matlab -batch otwin_conformance" --name matlab
otwin-conformance python --report conformance.json --badge badge.json
```

`--badge` writes a shields.io endpoint payload, so any repository can display its conformance status.

<br>

## Reference models live here, deliberately

A specification that can only be checked by running the thing it specifies is not a specification.

`otwin_spec.reference` contains ~200 lines of plain NumPy defining what `water_tank`, `dc_motor`, `pumped_hydro` and the two-body heat exchanger **are** in Otwin. Explicit RK4, no cleverness, no optional dependencies. If a tool package disagrees with one of these, the specification is right by definition and the disagreement is a bug report against the tool.

RK4 is used on purpose even though it is not structure-preserving: the fixtures must be passable by an ordinary integrator on a reasonable grid, so that a failure means a wrong *model* rather than a less sophisticated stepper. A tolerance tighter than RK4 can meet would turn this into a test of numerical methods rather than of physics.

<br>

## The Twin Manifest

`schemas/twin-manifest-1.0.json` defines how a fitted twin is exchanged. Three rules in it exist because each has already caused, or would cause, a silent failure across a language boundary:

1. **No `NaN` or `Infinity`.** They are not valid JSON ([RFC 8259 §6](https://www.rfc-editor.org/rfc/rfc8259#section-6)). Python emits them anyway as bare tokens; Julia's `JSON3`, MATLAB's `jsondecode` and `JSON.parse` all reject them. A diverged fit must fail at the point of writing, not months later in another language.
2. **Timestamps are `YYYY-MM-DDTHH:MM:SSZ`.** Julia's `Dates.DateTime` cannot parse an offset without `TimeZones.jl`; MATLAB's `datetime` needs an explicit format for microseconds.
3. **`leakage_free` must be a real boolean.** MATLAB and Julia both round-trip booleans to `1`, `0` or a string under some configurations, and the field that certifies honest validation must not accept those.

<br>

## Contributing

**The most useful contribution is a new fixture** — a physical system with a closed-form answer that no current fixture covers. Thermal, electrical, chemical, mechanical: all welcome.

A fixture needs four things:

1. a physical system and its parameters
2. a **closed-form** or otherwise analytically known result
3. a stated `rationale` — what would go wrong if this were not checked
4. a **mutant** that proves the check works

Requirement 4 is not optional. A check without a mutant is untested code protecting untested code.

Other ways in: adapters for new languages, tightening a tolerance with justification, translating the specification.

See [CONTRIBUTING.md](CONTRIBUTING.md) · practices follow [ColPrac](https://github.com/SciML/ColPrac).

<br>

## Documents

- **[The specification](spec/SPECIFICATION.md)** — normative, RFC 2119 language
- [`schemas/`](src/otwin_spec/schemas) — JSON Schema, consumed directly by Julia and MATLAB
- [`fixtures/`](src/otwin_spec/fixtures) — golden fixtures, one JSON file each
- [`otwin-base`](https://github.com/otwin-core/otwin-base) — the Python expression of the same contract

<br>

## How to cite

See [CITATION.cff](CITATION.cff).
