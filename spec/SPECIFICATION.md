# The Otwin Specification

**Version 1.0 · Draft · 3 August 2026**

This document is normative. Where it and any implementation disagree, this document is correct and the implementation has a bug.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be interpreted as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

---

## 1. Scope and purpose

Otwin is a collection of tools for building digital twins of physical assets. This specification defines the small set of things those tools must agree on so that they compose:

1. **What a twin is** — the interface (§3).
2. **What a fitted twin looks like on disk** — the Twin Manifest (§4).
3. **What it means to be correct** — the conformance suite (§5).

It deliberately does not specify algorithms. Any integrator, any estimator and any uncertainty method is permitted, provided the results satisfy §5.

### 1.1 Why a specification exists at all

Otwin has a Python reference implementation and bindings to Julia and MATLAB. Without a written contract with executable tests, three things happen, reliably:

- each language grows its own slightly different notion of what a model is;
- a fitted twin cannot move between them;
- "physics-informed" becomes a claim rather than a property, because nothing checks it.

The conformance suite is the answer to the third. A model asserting port-Hamiltonian structure is asserting something falsifiable, and §5 falsifies it.

---

## 2. Conformance

An implementation is **conformant** when the suite in `otwin-spec` reports no failures against it, and at least one fixture passes.

Three outcomes are distinguished, and the distinction matters:

| Outcome | Meaning | Blocks conformance |
|---|---|---|
| **pass** | The check ran and the result was within tolerance | no |
| **fail** | The check ran and the result was outside tolerance | **yes** |
| **skip** | The implementation reported no number for this check | yes, if *every* check skipped |
| **unsupported** | The implementation explicitly declared it does not implement this fixture | no |

An implementation MUST declare gaps rather than stay silent. A young binding that supports three fixtures and declares the rest unsupported is conformant-so-far and MUST advertise itself that way — it is far more useful than one that pretends.

An implementation MUST NOT be marked conformant on the basis of skipped checks alone. Silence is not conformance.

---

## 3. The interface

### 3.1 A twin model

Every model MUST provide:

```
n_states : integer >= 1
n_inputs : integer >= 0
rhs(x, u, t)     -> dx/dt,  shape (n_states,)
observe(x, u, t) -> y
```

### 3.2 A port-Hamiltonian model

A model MAY additionally declare port-Hamiltonian structure. If it does, it MUST provide `H(x)`, `J(x)`, `R(x)` and `g(x)`, and the following MUST hold for every reachable state:

$$\dot{x} = (J(x) - R(x))\,\nabla H(x) + g(x)\,u, \qquad y = g(x)^\top \nabla H(x)$$

- `J(x)` MUST be skew-symmetric: $J + J^\top = 0$.
- `R(x)` MUST be positive semidefinite: $\lambda_{\min}(R) \geq 0$.

These two properties are the entire reason the power balance

$$\frac{dH}{dt} = -\nabla H^\top R\, \nabla H + y^\top u \;\leq\; y^\top u$$

holds structurally rather than by fitting. With $u = 0$, energy MUST NOT increase — at any step size, over any horizon.

Declaring this structure and violating it is the most damaging thing an implementation can do, because the violation is invisible on a test set and shows up only in the long-horizon extrapolation the structure was supposed to protect. §5 checks both properties directly.

A model that can compute $\nabla H$ analytically SHOULD expose it as `grad_H(x)`. Tools MUST fall back to a numerical gradient when it is absent.

### 3.3 An irreversible port-Hamiltonian model

A model MAY declare irreversible structure (Ramírez, Maschke & Sbarbaro, 2013). If it does, it MUST provide `entropy_production(x, u, t)`, and

$$\sigma(x) \geq 0 \quad \text{for every reachable } x$$

MUST hold. This MUST be enforced structurally, not documented. An implementation that computes $\sigma$ and does not constrain it does not satisfy this clause.

### 3.4 An empirical-law model

Some systems only degrade. They have no energy function and no port. A model MAY declare empirical-law structure, providing `law(t, params)` and `param_names`.

An empirical-law model MUST NOT be required to provide `rhs`. Requiring a state derivative from a fade law — typically satisfied by returning zeros — is the most common conceptual error in this field, and this specification declines to institutionalise it.

### 3.5 The four verbs

Tools SHOULD expose these operations, unified across every model structure:

```
forecast(model, x0, t, u)       -> Forecast
evaluate(model, data, protocol) -> Report
calibrate(forecast, residuals)  -> Interval
assimilate(model, state, y)     -> state
```

This is the "unified API over a large collection of models" that makes the ecosystem composable: a new physical system is written once and every tool works on it immediately.

### 3.6 Evaluation

An implementation reporting forecast accuracy:

- MUST use a temporal split by default. Random splits measure interpolation, not forecasting.
- MUST report whether the protocol was leakage-free, and any report where it was not MUST say so before it says anything else.
- MUST compare against at least one baseline and report a skill score (model error ÷ baseline error).
- MUST NOT present $R^2$ as the headline metric for a forecasting task.

An implementation reporting uncertainty:

- MUST distinguish *nominal* from *empirically measured* coverage.
- MUST NOT present an interval as validated when its coverage has not been measured. Not-yet-checked is not the same as fine.

---

## 4. The Twin Manifest

A fitted twin is exchanged as a JSON document conforming to `schemas/twin-manifest-1.0.json`.

### 4.1 Required fields

`name`, `model_class`, `model_kind`, `n_states`, `n_inputs`, `provenance`.

`model_class` MUST be one of `port_hamiltonian`, `irreversible_phs`, `empirical_law`, `learned_phs`, `composite`.

### 4.2 White-box and grey-box

`estimated` lists the parameters fitted from data. It MUST be an array, MUST NOT contain duplicates, and every entry MUST be a key of `parameters`.

This single field carries the distinction the rest of the ecosystem branches on:

- **empty** → the twin is white-box, and MAY be validated against a closed-form answer;
- **non-empty** → the twin is grey-box, and MUST be validated against held-out data with a baseline.

### 4.3 Interoperability rules

These exist because they have each already caused, or would cause, a silent failure across a language boundary.

**4.3.1 — Non-finite numbers are forbidden.** A manifest MUST NOT contain `NaN` or `Infinity`. These are not valid JSON ([RFC 8259 §6](https://www.rfc-editor.org/rfc/rfc8259#section-6)); Python emits them anyway as bare tokens, and Julia's `JSON3`, MATLAB's `jsondecode` and JavaScript's `JSON.parse` all reject them. An implementation MUST fail when asked to write one, at the point of writing. A diverged fit belongs in `notes`, not in `parameters`.

**4.3.2 — Timestamps are second-resolution UTC with a `Z` suffix.** `provenance.created` MUST match `YYYY-MM-DDTHH:MM:SSZ`. Offsets and fractional seconds are forbidden: Julia's `Dates.DateTime` cannot parse an offset without `TimeZones.jl`, and MATLAB's `datetime` requires an explicit `InputFormat` for microseconds.

**4.3.3 — Booleans are booleans.** `validation.leakage_free` MUST be a JSON boolean. A reader MUST treat any value that is not exactly `true` as not validated. MATLAB and Julia both round-trip booleans to `1`, `0` or a string under some configurations, and the one field certifying honest validation must not accept those.

**4.3.4 — Unknown fields survive.** A reader MUST preserve fields it does not recognise, so that a manifest written by a newer implementation round-trips losslessly through an older one. A reader MUST warn on a major-version mismatch and MUST NOT fail on a minor one.

### 4.4 Provenance

Every quantitative claim SHOULD be traceable to a script, a commit and a seed. An implementation SHOULD populate `script`, `commit` and `seed` whenever it can. A number that cannot be regenerated is an anecdote.

---

## 5. The conformance suite

### 5.1 Architecture

An implementation is a **subprocess**. The runner writes a fixture to its standard input and reads a result document from its standard output. That is the whole integration surface, and it is why one suite can judge Python, Julia and MATLAB.

An adapter reports **numbers only**. It MUST NOT judge itself. All judgement happens in one place, in one language, from one source — otherwise a bug in a language's own checking code would hide a bug in that language's models.

### 5.2 The fixtures

Each fixture is a physical system whose correct behaviour follows from a closed-form result. They are not synthetic.

| Fixture | What it verifies | Ground truth |
|---|---|---|
| `phs_structure_water_tank` | `J` skew, `R` PSD at sampled states | algebraic identity |
| `water_tank_passivity` | energy never increases with the inflow off | `dH/dt ≤ 0` |
| `dc_motor_steady_state` | convergence to the analytic steady state | `ω_ss = VK/(R_e b + K²)` |
| `dc_motor_coastdown_passivity` | two coupled stores, no energy created | `dH/dt ≤ 0` |
| `pumped_hydro_conservation` | a sealed idle store holds its energy | `J = 0` ⟹ conservation |
| `iphs_second_law` | entropy production never negative | `σ ≥ 0` |
| `manifest_roundtrip` | schema validity, round-trip, NaN rejection | §4.3 |

Tolerances are stated per check and are chosen to be passable by a competent ordinary integrator — the suite tests physics, not numerical sophistication. Where a tolerance is not the mathematically exact bound, the fixture MUST state why. (`water_tank_passivity` is the current example: the reference model regularises `R` to zero below `h = 10⁻⁶`, so the state may freeze a few multiples of that below empty.)

### 5.3 The suite must have teeth

A conformance suite that only ever passes is decoration. `otwin-spec` therefore ships **mutants**: deliberately broken implementations, each with one physically meaningful defect, and tests asserting that each is caught by the check meant to catch it.

The current mutants are a non-skew `J`, a negative `R`, an energy-leaking integrator, a gyrator constant off by 10 %, a negative entropy production, a manifest writer that emits `NaN`, and a diverged run. The energy-leak mutant is detected at 0.003 % of initial energy.

Contributors adding a check SHOULD add the mutant that proves it works.

### 5.4 Failure reports

A failure MUST report the measured value, the tolerance, and the closed-form statement that was expected, so that the report is self-contained. "Failed" without a number is not an acceptable output.

---

## 6. Versioning

This specification uses `MAJOR.MINOR`.

- **MINOR** — fixtures added, tolerances loosened, optional fields added. A conformant implementation stays conformant.
- **MAJOR** — a required interface changes, a tolerance tightens, or a manifest field becomes required. Implementations may need work.

A change to the interface in `otwin-base` MUST ship with a matching change here in the same release.

---

## 7. References

1. van der Schaft, A. & Jeltsema, D. (2014). *Port-Hamiltonian Systems Theory: An Introductory Overview.* Foundations and Trends in Systems and Control, 1(2–3), 173–378. DOI: 10.1561/2600000002. — §3.2, and the DC motor fixture (Example 2.5, Eq. 2.30).
2. Ramírez, H., Maschke, B. & Sbarbaro, D. (2013). *Irreversible port-Hamiltonian systems: a general formulation with application to the CSTR.* Chemical Engineering Science, 89, 223–234. — §3.3.
3. Wang, J. et al. (2011). *Cycle-life model for graphite-LiFePO₄ cells.* Journal of Power Sources, 196(8), 3942–3948. — the empirical-law example.
4. Bray, T. (ed.) (2017). *The JavaScript Object Notation (JSON) Data Interchange Format.* RFC 8259. — §4.3.1.
5. Gneiting, T. & Raftery, A. E. (2007). *Strictly proper scoring rules, prediction, and estimation.* JASA, 102(477), 359–378. — §3.6.
6. Blakers, A., Stocks, M., Lu, B. & Cheng, C. (2021). *A review of pumped hydro energy storage.* Progress in Energy, 3(2), 022003. — the pumped-hydro fixture.
