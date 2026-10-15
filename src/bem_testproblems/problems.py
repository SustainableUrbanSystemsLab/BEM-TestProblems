# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2018, Christoph Waibel. All rights reserved.
# Continuous benchmark definitions derived from BEOBenchmark, commit 54736a6b899a488222ad3184f306c1f401daf4f9.
# See data/licenses/BEOBenchmark-LICENSE.txt for the complete license.
"""The ten continuous BEOBenchmark problems, in published problem order."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Mapping, Sequence

from .parameters import (
    DETAILED_PARAMETERS,
    OFFICE_PARAMETERS,
    SCHOOL_PARAMETERS,
    SIMPLE_PARAMETERS,
    Parameter,
)

UPSTREAM_COMMIT = "54736a6b899a488222ad3184f306c1f401daf4f9"
PAPER_DOI = "10.1016/j.enbuild.2019.01.048"
PROBLEM_IDS = (1, 2, 3, 4, 5, 6, 8, 9, 10, 13)


@dataclass(frozen=True)
class Problem:
    id: int
    name: str
    family: str
    parameters: tuple[Parameter, ...]
    template_filename: str
    weather_filename: str
    objective_unit: str
    constants: Mapping[str, float]
    fixed_parameters: Mapping[str, float] = field(default_factory=dict)
    source_references: tuple[str, ...] = ()
    paper_equation: int = 0
    paper_table: int = 0
    definition: str = "historical-implementation"

    def __post_init__(self):
        object.__setattr__(self, "constants", MappingProxyType(dict(self.constants)))
        object.__setattr__(self, "fixed_parameters", MappingProxyType(dict(self.fixed_parameters)))

    @property
    def dimension(self) -> int:
        return len(self.parameters)

    @property
    def bounds(self) -> tuple[tuple[float, float], ...]:
        return tuple(parameter.bounds for parameter in self.parameters)

    @property
    def midpoint(self) -> tuple[float, ...]:
        return tuple(parameter.midpoint for parameter in self.parameters)

    @property
    def design_day(self) -> bool:
        return self.family == "school"

    @property
    def provenance(self) -> dict:
        return {
            "upstream_commit": UPSTREAM_COMMIT,
            "paper_doi": PAPER_DOI,
            "paper_equation": self.paper_equation,
            "paper_table": self.paper_table,
            "source_references": self.source_references,
            "definition": self.definition,
        }

    def validate(self, x: Sequence[float]) -> tuple[float, ...]:
        try:
            values = tuple(x)
        except TypeError as exc:
            raise ValueError(f"Problem {self.id} requires {self.dimension} coordinates") from exc
        if len(values) != self.dimension:
            raise ValueError(
                f"Problem {self.id} requires {self.dimension} coordinates, received {len(values)}"
            )
        return tuple(parameter.validate(value) for parameter, value in zip(self.parameters, values))

    def expanded_vector(self, x: Sequence[float]) -> tuple[float, ...]:
        values = self.validate(x)
        if self.id != 8:
            return values
        by_name = {p.name: value for p, value in zip(self.parameters, values)}
        by_name.update(self.fixed_parameters)
        return tuple(by_name[parameter.name] for parameter in DETAILED_PARAMETERS)

    def objective_terms(self, x, outputs):
        from .losses import objective_terms

        return objective_terms(self, x, outputs)

    def outer_loss(self, x, outputs) -> float:
        from .losses import outer_loss

        return outer_loss(self, x, outputs)

    def outer_derivatives(self, x):
        from .losses import outer_derivatives

        return outer_derivatives(self, x)

    def penalty_metadata(self, x):
        from .losses import penalty_metadata

        return penalty_metadata(self, x)

    def render_legacy(self, x, path) -> Path:
        from .models import render_legacy

        return render_legacy(self, x, path)

    def render_modern(self, x, path) -> Path:
        from .models import render_modern

        return render_modern(self, x, path)

    def simulate_outputs(self, x, *, runner, weather=None) -> dict[str, float]:
        from .energyplus import SUPPORTED_VERSIONS
        from .outputs import extract_outputs

        self.validate(x)
        if weather is None and not self.design_day:
            raise ValueError(
                f"Problem {self.id} requires weather={self.weather_filename!r}; weather is not bundled"
            )
        version = str(runner.version)
        match = re.search(r"\b(\d+\.\d+(?:\.\d+)?)\b", version)
        if match is None:
            raise ValueError(f"Cannot identify EnergyPlus version {version!r}")
        selected_version = match.group(1)
        if selected_version.count(".") == 1:
            selected_version += ".0"
        if selected_version not in SUPPORTED_VERSIONS:
            raise ValueError(
                f"Supported EnergyPlus versions are {SUPPORTED_VERSIONS}, got {selected_version!r}"
            )
        legacy = selected_version == "8.5.0"
        with TemporaryDirectory(prefix=f"bem-problem-{self.id}-input-") as directory:
            path = Path(directory) / ("model.idf" if legacy else "model.epJSON")
            (self.render_legacy if legacy else self.render_modern)(x, path)
            run = runner.run(path, weather, design_day=self.design_day)
            return dict(extract_outputs(self.family, run))

    def evaluate(self, x, *, runner, weather=None) -> float:
        return self.outer_loss(x, self.simulate_outputs(x, runner=runner, weather=weather))


_SIMPLE_CONSTANTS = {
    "area_m2": 96.0,
    "heating_efficiency": 0.44,
    "cooling_efficiency": 0.77,
    "electricity_primary_factor": 3.0,
}
_DETAILED_CONSTANTS = {
    "area_m2": 1104.0,
    "electricity_primary_factor": 3.0,
    "gas_primary_factor": 1.0,
    "legacy_fan_multiplier": 2.0,
}
_OFFICE_CONSTANTS = {
    "gas_primary_factor": 1.092,
    "electricity_primary_factor": 3.095,
    "legacy_window_height_m": 0.5488,
    "paper_window_height_m": 0.55,
}
_SCHOOL_CONSTANTS = {
    "design_day_energy_cost_per_kwh": 2520.0 * 0.6 * 0.75 / (19.0 - -11.5) * 0.034,
    "design_day_rate_cost_per_kw": 12.42,
    "insulation_cost_per_m": 678.3,
    "insulation_cost_offset": -5.355,
    "radiator_cost_per_ua": 0.4375,
    "heating_degree_factor": 2520.0,
    "design_indoor_temperature_c": 19.0,
    "design_outdoor_temperature_c": -11.5,
}
_CLIMATES = (
    ("Seattle", "seattle", "USA_WA_Seattle-Tacoma.727930_TMY2.epw"),
    ("Houston", "houston", "USA_TX_Houston-Intercontinental.722430_TMY2.epw"),
    ("Chicago", "chicago", "USA_IL_Chicago-OHare.725300_TMY2.epw"),
)


def _make_problems() -> dict[int, Problem]:
    result = {}
    for index, (city, slug, weather) in enumerate(_CLIMATES, start=1):
        result[index] = Problem(
            index,
            f"Simple office - {city}",
            "simple",
            SIMPLE_PARAMETERS,
            f"simple_{slug}_template.idf",
            weather,
            "kWh/(m2 year)",
            _SIMPLE_CONSTANTS,
            source_references=(
                "GHEPlusRunParametric1to3.cs:118-160",
                "GHEPlusRunParametric1to3.cs:195-214",
            ),
            paper_equation=5,
            paper_table=3,
        )
        number = index + 3
        result[number] = Problem(
            number,
            f"Detailed office - {city}",
            "detailed",
            DETAILED_PARAMETERS,
            f"detailed_{slug}_template.idf",
            weather,
            "kWh/(m2 year)",
            _DETAILED_CONSTANTS,
            source_references=(
                "GHEPlusRunParametric4to8.cs:159-258",
                "GHEPlusRunParametric4to8.cs:294-355",
            ),
            paper_equation=6,
            paper_table=4,
        )
    result[8] = Problem(
        8,
        "Detailed office - Chicago, reduced",
        "detailed",
        tuple(p for p in DETAILED_PARAMETERS if p.source_index not in (10, 12)),
        "detailed_chicago_template.idf",
        _CLIMATES[2][2],
        "kWh/(m2 year)",
        _DETAILED_CONSTANTS,
        fixed_parameters={
            "summer_night_cooling_setpoint": 25.0,
            "cooling_supply_temperature": 12.0,
        },
        source_references=(
            "GHEPlusRunParametric4to8.cs:159-355",
            "Grasshopper/Problem8_reduced.gh:constant panels 25 and 12",
        ),
        paper_equation=6,
        paper_table=4,
    )
    for number, size in ((9, "Small"), (10, "Large")):
        source = f"GHEPlusRunParametric{number}.cs"
        result[number] = Problem(
            number,
            f"{size} office - San Francisco",
            "office",
            OFFICE_PARAMETERS,
            f"problem_{number}_template.idf",
            "USA_CA_San.Francisco.Intl.AP_TMY3.epw",
            "MJ/m2",
            _OFFICE_CONSTANTS,
            source_references=(f"{source}:119-218",),
            paper_equation=7,
            paper_table=5,
        )
    result[13] = Problem(
        13,
        "School - Belgrade",
        "school",
        SCHOOL_PARAMETERS,
        "Problem13_template.idf",
        "YUG_Belgrade_IWEC.epw",
        "EUR",
        _SCHOOL_CONSTANTS,
        source_references=(
            "GHEPlusRunParametric13.cs:102-153",
            "Input/Problem13_template.idf:55-81,14756-14762",
        ),
        paper_equation=10,
        paper_table=7,
    )
    return result


_PROBLEMS = _make_problems()


def get_problem(problem_id) -> Problem:
    if isinstance(problem_id, bool):
        raise ValueError(f"Expected one of {PROBLEM_IDS}")
    if isinstance(problem_id, str):
        match = re.fullmatch(r"[pP]?(\d+)", problem_id.strip())
        if not match:
            raise ValueError(f"Expected a problem number or p<number>, received {problem_id!r}")
        problem_id = int(match.group(1))
    if not isinstance(problem_id, int) or problem_id not in _PROBLEMS:
        raise ValueError(
            f"Only continuous problems {PROBLEM_IDS} are available; received {problem_id!r}"
        )
    return _PROBLEMS[problem_id]


def list_problems() -> tuple[Problem, ...]:
    return tuple(_PROBLEMS[number] for number in PROBLEM_IDS)
