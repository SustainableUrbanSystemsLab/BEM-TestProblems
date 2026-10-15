# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2018, Christoph Waibel. All rights reserved.
# Parameter definitions derived from BEOBenchmark, commit 54736a6b899a488222ad3184f306c1f401daf4f9.
# See data/licenses/BEOBenchmark-LICENSE.txt for the complete license.
"""Physical decision coordinates from the published continuous benchmark."""

from dataclasses import dataclass
from math import isfinite
from numbers import Real


@dataclass(frozen=True)
class Parameter:
    """One physical coordinate; ``source_index`` is its zero-based C# index."""

    name: str
    lower: float
    upper: float
    unit: str
    paper_symbol: str
    source_index: int
    description: str = ""

    @property
    def bounds(self) -> tuple[float, float]:
        return (self.lower, self.upper)

    @property
    def midpoint(self) -> float:
        return (self.lower + self.upper) / 2.0

    def validate(self, value: Real) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{self.name} must be a real number in {self.bounds}")
        number = float(value)
        if not isfinite(number) or not self.lower <= number <= self.upper:
            raise ValueError(f"{self.name}={number!r} is outside {self.bounds} {self.unit}")
        return number


def _parameter(name, lower, upper, unit, index, description=""):
    return Parameter(name, lower, upper, unit, f"x{index + 1}", index, description)


SIMPLE_PARAMETERS = (
    _parameter("orientation", -180.0, 180.0, "deg", 0),
    _parameter("west_window_width", 0.1, 5.9, "m", 1),
    _parameter("east_window_width", 0.1, 5.9, "m", 2),
    _parameter("shade_transmittance", 0.2, 0.8, "1", 3),
)

DETAILED_PARAMETERS = (
    _parameter("north_window_width", 1.224, 5.832, "m", 0),
    _parameter("west_window_width", 7.344, 25.668, "m", 1),
    _parameter("east_window_width", 7.344, 25.668, "m", 2),
    _parameter("south_window_width", 1.224, 5.832, "m", 3),
    _parameter("west_overhang_depth", 0.05, 1.05, "m", 4),
    _parameter("east_overhang_depth", 0.05, 1.05, "m", 5),
    _parameter("south_overhang_depth", 0.05, 1.05, "m", 6),
    _parameter("west_shading_setpoint", 100.0, 600.0, "W/m2", 7),
    _parameter("east_shading_setpoint", 100.0, 600.0, "W/m2", 8),
    _parameter("south_shading_setpoint", 100.0, 600.0, "W/m2", 9),
    _parameter("summer_night_cooling_setpoint", 20.0, 25.0, "degC", 10),
    _parameter("winter_night_cooling_setpoint", 20.0, 25.0, "degC", 11),
    _parameter("cooling_supply_temperature", 12.0, 18.0, "degC", 12),
)

OFFICE_PARAMETERS = tuple(
    _parameter(f"{direction}_window_{position}", lower, upper, "m", 2 * direction_index + offset)
    for direction_index, direction in enumerate(("north", "east", "south", "west"))
    for offset, position, lower, upper in ((0, "bottom", 0.8, 1.25), (1, "top", 1.35, 2.2))
) + (
    _parameter("cooling_supply_temperature", 12.0, 18.0, "degC", 8),
    _parameter("weekday_heating_setback", 13.0, 21.0, "degC", 9),
    _parameter("holiday_heating_setback", 13.0, 21.0, "degC", 10),
    _parameter("weekday_cooling_setback", 24.0, 36.0, "degC", 11),
    _parameter("holiday_cooling_setback", 24.0, 36.0, "degC", 12),
)

SCHOOL_PARAMETERS = (_parameter("insulation_thickness", 0.05, 0.3, "m", 0),) + tuple(
    _parameter(f"radiator_ua_{zone}", lower, upper, "W/K", index)
    for index, (zone, lower, upper) in enumerate(
        (
            ("class_zone_2", 400.0, 800.0),
            ("work_zone", 60.0, 120.0),
            ("kitchen_zone", 50.0, 110.0),
            ("music_zone", 80.0, 160.0),
            ("service_zone", 20.0, 50.0),
            ("washing_zone", 80.0, 180.0),
            ("big_zone", 140.0, 280.0),
            ("class_zone_1", 380.0, 760.0),
            ("office_zone", 350.0, 700.0),
        ),
        start=1,
    )
)
