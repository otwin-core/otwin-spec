# Changelog

## [Unreleased]

### Fixed — physics

Two of the four reference models were wrong. Both were found by independent
review rather than by any test, which is itself the argument for this package
existing.

- **Water tank was dimensionally inconsistent.** `R` was
  `c_d·a·√(2/h)/(ρgA)`, missing the `g` under the radical and one factor of
  `A`. The correct form is `c_d·a·√(2g/h)/(ρgA²)`. The old model produced
  `dh/dt` in units of m^2.5 and drained 3.13× too slowly, while still yielding
  a smooth, entirely plausible decay curve. **This error originated in the
  upstream `otwin` library (`src/otwin/systems/library.py`) and is present
  there too.**
- **The two-body heat exchanger violated the first law.** Putting the heat flow
  in `R` gave a closed system that conserved *entropy* and destroyed *energy* —
  the exact inverse of thermodynamics — while still reporting a plausible
  non-negative `σ`, because `σ` was computed from a formula rather than from
  the dynamics. Rewritten with the irreversibility in a modulated skew matrix,
  `ẋ = γ(x)J₀∇H`, `γ = λ(T₁−T₂)/(T₁T₂)`. Now `dU/dt = 0` to 1.3e-13 and
  `S₁+S₂` rises by 2.56 over the fixture horizon.

### Fixed — the suite could be passed without any physics

- **Fixtures no longer ship their answers to the adapter.** `run_fixture` sent
  the whole fixture, including `checks[].expected`, `bound` and `max_drift`. A
  60-line adapter that echoed those back scored 8/8 bright green with no model
  and no integrator. `runner.as_task()` now strips `checks`, `rationale` and
  `derived_quantities`. The fabricating adapter is kept permanently as
  `tests/mutants.py fabricator`, with a test asserting it stays caught.
- **NaN no longer passes the matrix checks.** `max()` and `min()` silently
  swallow NaN, so `J = [[NaN]]` and `R = [[NaN]]` passed both skew-symmetry and
  PSD. Finiteness guards added to the matrix and bound checks.
- **`rejects_non_finite` was self-graded.** The adapter reported a boolean about
  its own behaviour — the one place the suite let an implementation grade its
  own work. It now reports evidence (the exception raised, or the bytes
  written) and the runner judges.
- **A fixture whose checks all skipped counted as passed.** An adapter
  reporting nothing therefore earned a green badge. Silence is now explicitly
  not conformance.

### Changed — fixtures

- `pumped_hydro_conservation`: the drift tolerance was measured from the
  reference implementation, which the fixture's own rationale admitted. It is
  now derived analytically from `c(p_u−p_l)²T/H(0)`, the penstock parameter `c`
  is stated in the fixture, and a monotonicity check was added so that energy
  *creation* can no longer pass a two-sided drift bound.
- `iphs_second_law`: `σ ≥ 0` alone was far too weak — a model conserving
  entropy passes it. Now also checks that internal energy is conserved and that
  total entropy actually rises. The sample state `[1.0, 2.0]` was exactly
  thermal equilibrium (`σ = 0` identically) and has been replaced.
- Water tank split into `water_tank_drain_law` (exact Torricelli solution,
  matched to 1.5e-13) and `water_tank_passivity` (run past emptying). The
  passivity fixture previously depended on the grid: `H = ½ρgAh²` is even in
  `h`, so an overshoot below empty read back as an energy gain, and whether it
  passed depended on where the final step landed. The head is now clamped.
- All fixtures state every parameter they need. Keys beginning with `_` are
  documentation and are ignored by adapters.

### Added

- `fixture-1.0.json` and `result-1.0.json` schemas — previously referenced but
  absent, leaving third-party adapter authors without a normative contract.
- `strictly_increasing` check kind.
- `Estimator` and `HasEnergyGradient` protocols in `otwin-base`.

### Known limitations

- The fabricator is caught by 7 of 8 fixtures. `phs_structure_water_tank`
  passes it, because zero matrices are both skew-symmetric and positive
  semidefinite. Matrix checks validate a *reported matrix*, never the model
  that produced the trajectory, and four sampled states prove nothing about the
  rest of the state space. Closing this needs cross-consistency checks —
  verifying `energy == H(state)` and `ẋ ≈ (J−R)∇H + gu`. Open work.
