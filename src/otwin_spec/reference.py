"""Reference models for the conformance fixtures.

Why these live in the specification, not in a tool package
-----------------------------------------------------------

A specification that can only be checked by running the thing it specifies is
not a specification. These ~200 lines of NumPy are the executable definition of
what ``water_tank``, ``dc_motor``, ``pumped_hydro`` and the two-body heat
exchanger *are* in Otwin. Every implementation — including the main Python
library — is judged against them.

They are deliberately plain: explicit Euler and RK4, no cleverness, no optional
dependencies. Speed is irrelevant here; being obviously correct is the whole
job. If one of these disagrees with a tool package, the specification is the
one that is right by definition, and the disagreement is a bug report against
the tool.

Each model exposes ``H``, ``J``, ``R``, ``g`` and ``grad_H`` as plain
functions, matching the ``PortHamiltonianModel`` and ``HasEnergyGradient``
protocols in ``otwin-base`` without importing it — the specification must not
depend on any implementation.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

__all__ = ["ReferencePHS", "MODELS", "simulate", "build"]


@dataclass
class ReferencePHS:
    """A port-Hamiltonian system defined by its four structural functions.

    Attributes:
        H: Energy ``H(x) -> float``.
        grad_H: Energy gradient ``∇H(x) -> (n,)``.
        J: Interconnection ``J(x) -> (n, n)``, skew-symmetric.
        R: Dissipation ``R(x) -> (n, n)``, positive semidefinite.
        g: Port map ``g(x) -> (n, m)``.
        n_states: State dimension.
        n_inputs: Input dimension.
        entropy_production: For irreversible systems, ``σ(x, u) -> float >= 0``.
    """

    H: Callable[[np.ndarray], float]
    grad_H: Callable[[np.ndarray], np.ndarray]
    J: Callable[[np.ndarray], np.ndarray]
    R: Callable[[np.ndarray], np.ndarray]
    g: Callable[[np.ndarray], np.ndarray]
    n_states: int
    n_inputs: int
    entropy_production: Callable[[np.ndarray, np.ndarray], float] | None = None

    def rhs(self, x: np.ndarray, u: np.ndarray, t: float = 0.0) -> np.ndarray:
        """``ẋ = (J - R) ∇H + g u``."""
        return (self.J(x) - self.R(x)) @ self.grad_H(x) + self.g(x) @ np.atleast_1d(u)

    def observe(self, x: np.ndarray, u: np.ndarray, t: float = 0.0) -> np.ndarray:
        """``y = gᵀ ∇H``."""
        return self.g(x).T @ self.grad_H(x)

    def power_balance(self, x: np.ndarray, u: np.ndarray) -> float:
        """``dH/dt`` computed structurally, for cross-checking an integrator."""
        gh = self.grad_H(x)
        return float(-gh @ self.R(x) @ gh + self.observe(x, u) @ np.atleast_1d(u))


# --------------------------------------------------------------------------
# The models
# --------------------------------------------------------------------------


def water_tank(
    A: float = 1.0, a: float = 0.1, g: float = 9.81, c_d: float = 0.6, rho: float = 1000.0
) -> ReferencePHS:
    """A draining tank. Gravitational potential energy, dissipated by the outlet.

    ``H = ½ ρ g A h²``, ``J = 0`` (nothing circulates in one dimension),
    ``R`` is the outlet, ``g = 1/A`` (inflow raises the level).

    The dissipation is state-dependent because Torricelli's law is nonlinear.
    Requiring ``R ∇H`` to reproduce ``c_d·a·√(2gh)/A`` (the rate of change of
    *head*, not of volume) gives

    .. math:: R = \\frac{c_d\\,a\\,\\sqrt{2g/h}}{\\rho\\,g\\,A^{2}}

    Two details matter and are easy to get wrong:

    * The ``g`` under the radical and the second factor of ``A`` are both
      load-bearing. Dropping them yields ``dh/dt`` in units of m^2.5 and a tank
      that drains 3.13x too slowly. This exact error was present in an earlier
      implementation and was caught only by dimensional analysis during review —
      never by a test, because the trajectory still looked entirely plausible.
    * ``H = ½ρgAh²`` is **even in h**, so a step that overshoots below empty
      reads back as *increased* energy and a passivity check would fail for a
      numerical reason rather than a physical one. The state is therefore
      clamped at zero and ``R`` regularised below ``h = 1e-9``: an empty tank
      stays empty. Without the clamp, whether the fixture passes depends on
      where the final step lands relative to zero — that is, on the grid.
    """

    def _h(x):
        """Head, clamped at empty. A tank cannot hold a negative depth."""
        return max(float(x[0]), 0.0)

    def H(x):
        return float(0.5 * rho * g * A * _h(x) ** 2)

    def grad_H(x):
        return np.array([rho * g * A * _h(x)])

    def J(x):
        return np.zeros((1, 1))

    def R(x):
        h = _h(x)
        if h < 1e-9:
            return np.zeros((1, 1))
        return np.array([[c_d * a * math.sqrt(2.0 * g / h) / (rho * g * A * A)]])

    def g_mat(x):
        return np.array([[1.0 / A]])

    return ReferencePHS(H, grad_H, J, R, g_mat, n_states=1, n_inputs=1)


def dc_motor(
    L: float = 0.5, inertia: float = 0.01, Re: float = 1.0, b: float = 0.1, K: float = 0.5
) -> ReferencePHS:
    """A DC motor: two energy stores coupled by a gyrator.

    State ``x = [φ, p]`` — inductor flux-linkage and rotor angular momentum.
    ``H = φ²/2L + p²/2J``; ``J = [[0, -K], [K, 0]]`` is the lossless gyrator;
    ``R = diag(Re, b)`` is armature resistance and viscous friction.

    Reference: van der Schaft & Jeltsema (2014), Example 2.5, Eq. (2.30).

    Steady state under constant ``V`` follows by setting ``ẋ = 0``:
    ``ω_ss = VK/(Re·b + K²)`` and ``I_ss = Vb/(Re·b + K²)``.
    """

    def H(x):
        return float(0.5 * x[0] ** 2 / L + 0.5 * x[1] ** 2 / inertia)

    def grad_H(x):
        return np.array([x[0] / L, x[1] / inertia])

    def J(x):
        return np.array([[0.0, -K], [K, 0.0]])

    def R(x):
        return np.array([[Re, 0.0], [0.0, b]])

    def g_mat(x):
        return np.array([[1.0], [0.0]])

    return ReferencePHS(H, grad_H, J, R, g_mat, n_states=2, n_inputs=1)


def pumped_hydro(
    A_u: float = 5.0e4,
    A_l: float = 5.0e6,
    z_u: float = 300.0,
    g: float = 9.81,
    rho: float = 1000.0,
    c: float = 1.0e-9,
) -> ReferencePHS:
    """Two reservoirs and a reversible pump-turbine.

    State ``x = [V_u, V_l]`` — the stored volumes.
    ``H = ρg[z_u V_u + V_u²/2A_u + V_l²/2A_l]`` is gravitational potential
    energy. ``J = 0``: there is no lossless circulation path between the
    reservoirs, so water moves only through the penstock (``R``) or the
    pump-turbine port (``g``). That is exactly why a sealed, idle store
    conserves its energy.
    """

    def H(x):
        v_u, v_l = x[0], x[1]
        return float(rho * g * (z_u * v_u + v_u**2 / (2.0 * A_u) + v_l**2 / (2.0 * A_l)))

    def grad_H(x):
        return np.array([rho * g * (z_u + x[0] / A_u), rho * g * (x[1] / A_l)])

    def J(x):
        return np.zeros((2, 2))

    def R(x):
        return np.array([[c, -c], [-c, c]])

    def g_mat(x):
        return np.array([[1.0], [-1.0]])

    return ReferencePHS(H, grad_H, J, R, g_mat, n_states=2, n_inputs=1)


def heat_exchanger_2body(
    C1: float = 1.0, C2: float = 2.0, lam: float = 0.5, **kw
) -> ReferencePHS:
    """Two bodies exchanging heat — the smallest irreversible PHS.

    State ``x = [S₁, S₂]`` — the entropies. Internal energy is
    ``U = C₁ exp(S₁/C₁) + C₂ exp(S₂/C₂)``, so temperature is
    ``Tᵢ = ∂U/∂Sᵢ = exp(Sᵢ/Cᵢ)``, always positive.

    Fourier conduction transfers heat ``Q = λ(T₁ − T₂)``, so

    .. math:: \\dot S_1 = -Q/T_1, \\qquad \\dot S_2 = +Q/T_2

    from which both laws follow *identically*, not approximately:

    .. math::

        \\frac{dU}{dt} = T_1 \\dot S_1 + T_2 \\dot S_2 = -Q + Q = 0
        \\qquad \\text{(first law: the system is closed)}

    .. math::

        \\sigma = \\dot S_1 + \\dot S_2
        = \\frac{\\lambda (T_1 - T_2)^2}{T_1 T_2} \\geq 0
        \\qquad \\text{(second law)}

    **The irreversibility lives in a modulated skew matrix, not in R.** This is
    the whole point of the irreversible formulation, and the thing that is easy
    to get wrong. Writing the heat flow as a dissipation ``R`` produces a system
    that conserves *entropy* and destroys *energy* — the exact inverse of
    thermodynamics — while still reporting a plausible non-negative σ, because σ
    was computed from a formula rather than from the dynamics. An earlier
    version of this model did precisely that, and nothing caught it. The fixture
    now checks that ``U`` is conserved and that σ equals the measured
    ``d(S₁+S₂)/dt`` along a trajectory, so the formula can no longer disagree
    with the model that reports it.

    Here ``ẋ = γ(x) J₀ ∇H`` with ``γ = λ(T₁−T₂)/(T₁T₂)`` and
    ``J₀ = [[0, −1], [1, 0]]``. ``γJ₀`` is skew at every state, so the structure
    is a genuine port-Hamiltonian one; the state-dependence of ``γ`` is what
    makes it irreversible.

    Note that ``H`` here is internal energy and the states are entropies, so the
    correct expectation is that energy is *conserved*, not that it decays.
    Passivity checks do not apply to this system.

    Reference: Ramírez, Maschke & Sbarbaro (2013).
    """
    lam = kw.get("lambda", lam)

    def temps(x):
        return math.exp(x[0] / C1), math.exp(x[1] / C2)

    def H(x):
        return float(C1 * math.exp(x[0] / C1) + C2 * math.exp(x[1] / C2))

    def grad_H(x):
        T1, T2 = temps(x)
        return np.array([T1, T2])

    def _gamma(x):
        T1, T2 = temps(x)
        return lam * (T1 - T2) / (T1 * T2)

    def J(x):
        return _gamma(x) * np.array([[0.0, -1.0], [1.0, 0.0]])

    def R(x):
        return np.zeros((2, 2))

    def g_mat(x):
        return np.zeros((2, 1))

    def sigma(x, u=None):
        T1, T2 = temps(x)
        return float(lam * (T1 - T2) ** 2 / (T1 * T2))

    return ReferencePHS(
        H, grad_H, J, R, g_mat, n_states=2, n_inputs=1, entropy_production=sigma
    )


# Annotated so mypy knows what comes out of it. Without this the values are
# inferred as four distinct concrete function types and `MODELS[kind](**kwargs)`
# is "call of unknown type" -- which is the kind of error that makes people turn
# --strict off rather than fix it.
MODELS: dict[str, Callable[..., ReferencePHS]] = {
    "water_tank": water_tank,
    "dc_motor": dc_motor,
    "pumped_hydro": pumped_hydro,
    "heat_exchanger_2body": heat_exchanger_2body,
}


def build(kind: str, parameters: dict) -> ReferencePHS:
    """Instantiate a reference model by fixture ``model_kind``.

    Keys beginning with an underscore are documentation, not parameters, and
    are ignored. Fixtures use them to record units and modelling notes next to
    the numbers they annotate — ``"_units": "A, a in m^2; g in m/s^2"`` — so
    that a person writing an adapter in another language has the information
    without having to read this file. Every adapter MUST apply the same rule.
    """
    if kind not in MODELS:
        raise KeyError(f"unknown model_kind {kind!r}; known: {sorted(MODELS)}")
    kwargs = {k: v for k, v in parameters.items() if not k.startswith("_")}
    return MODELS[kind](**kwargs)


def simulate(
    model: ReferencePHS, x0: np.ndarray, t: np.ndarray, u: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Integrate with classical RK4 on the given grid.

    RK4 is not structure-preserving in general. It is used here deliberately:
    the fixtures must be passable by an ordinary integrator on a reasonable
    grid, so that a failure indicates a wrong *model*, not merely a
    less-sophisticated stepper. A tolerance tighter than RK4 can meet would
    turn the suite into a test of numerical methods rather than of physics.

    Returns:
        ``(X, energy)`` — the trajectory and ``H`` along it.
    """
    n = len(t)
    X = np.zeros((n, model.n_states))
    X[0] = x0
    for i in range(n - 1):
        dt = float(t[i + 1] - t[i])
        ui = np.atleast_1d(u[i])
        x = X[i]
        k1 = model.rhs(x, ui, t[i])
        k2 = model.rhs(x + 0.5 * dt * k1, ui, t[i] + 0.5 * dt)
        k3 = model.rhs(x + 0.5 * dt * k2, ui, t[i] + 0.5 * dt)
        k4 = model.rhs(x + dt * k3, ui, t[i] + dt)
        X[i + 1] = x + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
    energy = np.array([model.H(X[i]) for i in range(n)])
    return X, energy
