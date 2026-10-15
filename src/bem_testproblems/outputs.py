"""Extract the historical observables by report names and checked units.

The C# implementation selected fixed ESO/CSV rows. These mappings preserve the
selected quantities, including its supply-fan duplication and the school's
daily *average* heating rate. They do not silently reinterpret the objectives.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path

from .energyplus import RunResult


class OutputError(ValueError):
    """A required report is absent, ambiguous, malformed or has unexpected units."""


def _normal(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _finite(value: str, location: str) -> float:
    try:
        number = float(value)
    except ValueError as error:
        raise OutputError(f"Non-numeric report value {value!r} in {location}") from error
    if not math.isfinite(number):
        raise OutputError(f"Non-finite report value in {location}")
    return number


@dataclass(frozen=True)
class ESOVariable:
    report_id: str
    key: str
    name: str
    unit: str
    frequency: str
    values: tuple[float, ...]


def read_eso(path: str | Path) -> tuple[ESOVariable, ...]:
    """Read named Output:Variable dictionaries and their primary data values.

    ESO's additional extrema/time columns are deliberately not substituted for
    the primary value. For a Daily rate that value is the daily average.
    """
    path = Path(path)
    if not path.is_file():
        raise OutputError(f"Missing EnergyPlus output: {path}")
    dictionary: dict[str, tuple[str, str, str, str]] = {}
    values: dict[str, list[float]] = {}
    in_dictionary = True
    ended = False
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        for line_number, fields in enumerate(csv.reader(handle), start=1):
            if not fields:
                continue
            first = fields[0].strip()
            if first == "End of Data Dictionary":
                in_dictionary = False
                continue
            if first == "End of Data":
                ended = True
                break
            if in_dictionary:
                if len(fields) < 4 or not first.isdigit() or int(first) <= 5:
                    continue
                description = re.fullmatch(r"\s*(.*?)\s*\[([^]]*)\]\s*!\s*(\w+).*", fields[3])
                if description is None:
                    continue
                if first in dictionary:
                    raise OutputError(f"Duplicate ESO dictionary ID {first} in {path}")
                name, unit, frequency = description.groups()
                dictionary[first] = (fields[2].strip(), name.strip(), unit.strip(), frequency)
                values[first] = []
            elif first in dictionary:
                if len(fields) < 2:
                    raise OutputError(f"Truncated ESO data at {path}:{line_number}")
                values[first].append(_finite(fields[1], f"{path}:{line_number}"))
    if in_dictionary or not ended:
        raise OutputError(f"Incomplete ESO output: {path}")
    return tuple(ESOVariable(report_id, *entry, tuple(values[report_id]))
                 for report_id, entry in dictionary.items())


def _one(entries: tuple[ESOVariable, ...], key: str, names: tuple[str, ...],
         unit: str = "J", frequency: str = "RunPeriod") -> float:
    matches = [entry for entry in entries if _normal(entry.key) == _normal(key)
               and _normal(entry.name) in {_normal(name) for name in names}
               and _normal(entry.frequency) == _normal(frequency)]
    if len(matches) != 1:
        raise OutputError(f"Expected one {frequency} {key!r}/{names!r} report; found {len(matches)}")
    entry = matches[0]
    if entry.unit != unit:
        raise OutputError(f"Expected [{unit}] for {key}/{entry.name}; found [{entry.unit}]")
    if len(entry.values) != 1:
        raise OutputError(f"Expected one {frequency} value for {key}/{entry.name}; found {len(entry.values)}")
    return entry.values[0]


LIGHTS = ("Zone Lights Electric Energy", "Zone Lights Electricity Energy")
HEATING = ("Heating Coil Gas Energy", "Heating Coil NaturalGas Energy")
COOLING = ("Cooling Coil Electric Energy", "Cooling Coil Electricity Energy")
FAN = ("Fan Electric Energy", "Fan Electricity Energy")


def _office_y(path: Path) -> float:
    if not path.is_file():
        raise OutputError(f"Missing EnergyPlus tabular output: {path}")
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = [[cell.strip() for cell in row] for row in csv.reader(handle)]
    in_table = False
    column = None
    found = []
    for row in rows:
        if any(_normal(cell) == "site and source energy" for cell in row):
            in_table, column = True, None
            continue
        if not in_table:
            continue
        for index, cell in enumerate(row):
            compact = re.sub(r"\s+", "", cell.casefold())
            if "energyperconditionedbuildingarea" in compact:
                if not re.search(r"\[mj/(?:m2|m\^2|m²)\]", compact):
                    raise OutputError(f"Expected conditioned-area energy in [MJ/m2], found {cell!r}")
                column = index
        if any(_normal(cell) == "total source energy" for cell in row):
            if column is None or len(row) <= column:
                raise OutputError("Missing Total Source Energy conditioned-area column [MJ/m2]")
            # Keep EnergyPlus's displayed precision; recomputing energy / area
            # from other rounded cells changes the original C# objective.
            found.append(_finite(row[column], str(path)))
            in_table = False
    if len(found) != 1:
        raise OutputError(f"Expected one Site and Source Energy / Total Source Energy table in {path}")
    return found[0]


def extract_outputs(family: str, run: RunResult) -> dict[str, float]:
    """Return canonical observables; energies are kWh, rates kW, office Y MJ/m²."""
    directory = Path(run.directory)
    if family == "office":
        return {"Y": _office_y(directory / "eplustbl.csv")}
    if family not in {"simple", "detailed", "school"}:
        raise ValueError(f"Unknown benchmark output family {family!r}")
    entries = read_eso(directory / "eplusout.eso")
    if family == "simple":
        return {
            "Q_h": _one(entries, "ZONE1AIR", ("Zone Ideal Loads Supply Air Sensible Heating Energy",)) / 3.6e6,
            "Q_c": _one(entries, "ZONE1AIR", ("Zone Ideal Loads Supply Air Sensible Cooling Energy",)) / 3.6e6,
            "E_L": _one(entries, "ZONE ONE", LIGHTS) / 3.6e6,
        }
    if family == "school":
        return {
            "Q": _one(entries, "HOTWATER", ("District Heating Hot Water Energy", "District Heating Water Energy"),
                      frequency="Daily") / 3.6e6,
            "P": _one(entries, "HOTWATER", ("District Heating Hot Water Rate", "District Heating Water Rate"),
                      unit="W", frequency="Daily") / 1000.0,
        }
    zones = ("NORTH", "WEST", "EAST", "SOUTH", "INTERIOR")
    result = {f"H_{index}": _one(entries, f"ZONE {zone} ZONE COIL", HEATING) / 3.6e6
              for index, zone in enumerate(zones, start=1)}
    result["H_6"] = _one(entries, "MAIN HEATING COIL 1", HEATING) / 3.6e6
    result["C"] = _one(entries, "MAIN COOLING COIL 1", COOLING) / 3.6e6
    for zone, suffix in zip(zones, ("N", "W", "E", "S", "I")):
        result[f"L_{suffix}"] = _one(entries, f"ZONE {zone}", LIGHTS) / 3.6e6
    # Verified against genuine 8.5 ESO dictionary: old row 34 is SUPPLY FAN 1.
    result["V_legacy"] = _one(entries, "SUPPLY FAN 1", FAN) / 3.6e6
    result["V_return"] = _one(entries, "RETURN FAN 1", FAN) / 3.6e6
    return result
