# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2018, Christoph Waibel. All rights reserved.
# Objective algebra translated from BEOBenchmark, commit 54736a6b899a488222ad3184f306c1f401daf4f9.
# See data/licenses/BEOBenchmark-LICENSE.txt for the complete license.
"""Known outer losses, independently callable without EnergyPlus.

Outputs are energies in kWh, except office ``Y`` (MJ/m2) and school ``P``
(daily-average kW). These are observables, not least-squares residuals.
"""

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Mapping, Sequence

if TYPE_CHECKING:
    from .problems import Problem


def _value(outputs: Mapping[str, float], key: str) -> float:
    try:
        value = float(outputs[key])
    except KeyError as exc:
        raise ValueError(f"Missing simulator observable {key!r}") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Simulator observable {key!r} must be a finite number") from exc
    if not isfinite(value):
        raise ValueError(f"Simulator observable {key!r} must be finite")
    return value


def penalty_metadata(problem: "Problem", x: Sequence[float]) -> dict:
    """Return the original office step penalty and its known affine tests.

    The C# boundary comparison is ``>= 0`` with threshold 0.5488 m. The
    paper uses 0.55 m. An infeasible window is still simulated in the original
    benchmark; this function does not turn it into a simulator failure.
    """
    coordinates = problem.validate(x)
    if problem.family != "office":
        return {"values": (), "violated": (), "factor": 1.0, "jacobian": (), "differentiable": True}
    threshold = problem.constants["legacy_window_height_m"]
    values = tuple(coordinates[2 * j] - coordinates[2 * j + 1] + threshold for j in range(4))
    violated = tuple(value >= 0.0 for value in values)
    jacobian = tuple(
        tuple(
            1.0 if i == 2 * j else -1.0 if i == 2 * j + 1 else 0.0 for i in range(problem.dimension)
        )
        for j in range(4)
    )
    return {
        "values": values,
        "violated": violated,
        "factor": 1.0 + 0.5 * sum(violated),
        "jacobian": jacobian,
        "threshold_m": threshold,
        "paper_threshold_m": problem.constants["paper_window_height_m"],
        "comparison": ">= 0",
        "differentiable": all(abs(value) > 1e-12 for value in values),
        "source": "GHEPlusRunParametric9.cs:134-139; GHEPlusRunParametric10.cs:139-144",
    }


def objective_terms(
    problem: "Problem", x: Sequence[float], outputs: Mapping[str, float]
) -> dict[str, float]:
    """Return additive terms in the original scalar objective's units."""
    coordinates = problem.validate(x)
    c = problem.constants
    if problem.family == "simple":
        area = c["area_m2"]
        return {
            "heating": _value(outputs, "Q_h") / c["heating_efficiency"] / area,
            "cooling": _value(outputs, "Q_c") / c["cooling_efficiency"] / area,
            "lighting": _value(outputs, "E_L") * c["electricity_primary_factor"] / area,
        }
    if problem.family == "detailed":
        area, pef = c["area_m2"], c["electricity_primary_factor"]
        heat = sum(_value(outputs, f"H_{i}") for i in range(1, 7))
        light = (
            5.0 * _value(outputs, "L_N")
            + _value(outputs, "L_W")
            + _value(outputs, "L_E")
            + 5.0 * _value(outputs, "L_S")
            + _value(outputs, "L_I")
        )
        return {
            "heating": heat * c["gas_primary_factor"] / area,
            "cooling": _value(outputs, "C") * pef / area,
            "lighting": light * pef / area,
            # Exact historical behavior: the same ESO row is used twice.
            "fans": 2.0 * _value(outputs, "V_legacy") * pef / area,
        }
    if problem.family == "office":
        base = _value(outputs, "Y")
        factor = penalty_metadata(problem, coordinates)["factor"]
        return {"source_energy": base, "window_penalty": (factor - 1.0) * base}
    if problem.family == "school":
        return {
            "energy": c["design_day_energy_cost_per_kwh"] * _value(outputs, "Q")
            + c["design_day_rate_cost_per_kw"] * _value(outputs, "P"),
            "insulation": c["insulation_cost_per_m"] * coordinates[0] + c["insulation_cost_offset"],
            "radiators": c["radiator_cost_per_ua"] * sum(coordinates[1:]),
        }
    raise ValueError(f"Unknown objective family: {problem.family}")


def outer_loss(problem: "Problem", x: Sequence[float], outputs: Mapping[str, float]) -> float:
    """Evaluate the known outer map; it never launches a simulator."""
    terms = objective_terms(problem, x, outputs)
    if problem.family == "office":
        # Match the original multiplication instead of summing its decomposition.
        return penalty_metadata(problem, x)["factor"] * _value(outputs, "Y")
    return sum(terms.values())


@dataclass(frozen=True)
class OuterDerivatives:
    """Derivatives of phi(x,s), not the unknown full simulator composition."""

    output_gradient: Mapping[str, float]
    direct_gradient: tuple[float, ...] | None
    output_hessian: tuple[tuple[float, ...], ...]
    differentiable: bool
    penalty_jacobian: tuple[tuple[float, ...], ...] = ()


def outer_derivatives(problem: "Problem", x: Sequence[float]) -> OuterDerivatives:
    """Known partial derivatives, with office jump boundaries marked explicitly."""
    problem.validate(x)
    c = problem.constants
    direct = [0.0] * problem.dimension
    differentiable = True
    jacobian = ()
    if problem.family == "simple":
        area = c["area_m2"]
        weights = {
            "Q_h": 1.0 / c["heating_efficiency"] / area,
            "Q_c": 1.0 / c["cooling_efficiency"] / area,
            "E_L": c["electricity_primary_factor"] / area,
        }
    elif problem.family == "detailed":
        area, pef = c["area_m2"], c["electricity_primary_factor"]
        weights = {f"H_{i}": c["gas_primary_factor"] / area for i in range(1, 7)}
        weights.update({"C": pef / area, "V_legacy": 2.0 * pef / area})
        weights.update(
            {
                f"L_{side}": pef * (5.0 if side in ("N", "S") else 1.0) / area
                for side in ("N", "W", "E", "S", "I")
            }
        )
    elif problem.family == "office":
        penalty = penalty_metadata(problem, x)
        weights = {"Y": penalty["factor"]}
        differentiable, jacobian = penalty["differentiable"], penalty["jacobian"]
    elif problem.family == "school":
        weights = {"Q": c["design_day_energy_cost_per_kwh"], "P": c["design_day_rate_cost_per_kw"]}
        direct = [c["insulation_cost_per_m"]] + [c["radiator_cost_per_ua"]] * 9
    else:
        raise ValueError(f"Unknown objective family: {problem.family}")
    zeros = tuple(tuple(0.0 for _ in weights) for _ in weights)
    return OuterDerivatives(
        weights, tuple(direct) if differentiable else None, zeros, differentiable, jacobian
    )
