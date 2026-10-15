#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Generate independent SYNTHETIC-CI weather; never canonical benchmark data.

This standard-library generator creates 8,760 hourly EPW records for a non-leap
year. No measured weather, TMY/IWEC records or third-party dataset is read/copied.
City coordinates identify four test locations; all climate coefficients are
arbitrary analytic test inputs, not estimates of a historical typical year.

Algorithms (hours are represented by their midpoint):
* dry bulb = prescribed mean + seasonal sine + diurnal sine;
* dew point = dry bulb - 6 C, with relative humidity from a smooth saturation
  vapor-pressure ratio, clipped to the physical 1–100 percent interval;
* solar elevation uses a sinusoidal declination and a local-solar-hour angle;
* direct/diffuse radiation is prescribed analytically during daylight, with
  global horizontal radiation equal to direct * sin(elevation) + diffuse;
* wind, pressure, infrared radiation and other fields are deterministic analytic
  values. Precipitation and snow are zero throughout these artificial years.

The simplified solar clock intentionally omits longitude/time-zone correction,
the equation of time, terrain, cloud dynamics and measured observations. These
files exercise parsers/simulators and same-weather reference-code parity. They
are unsuitable as paper reference values, canonical benchmark weather or design
climate data. Existing problem weather metadata is not modified.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class Climate:
    state: str
    latitude: float
    longitude: float
    time_zone: int
    elevation: float
    mean_temperature: float
    seasonal_amplitude: float
    diurnal_amplitude: float


CLIMATES = {
    "seattle": Climate("WA", 47.45, -122.30, -8, 122, 12, 8, 3),
    "houston": Climate("TX", 29.98, -95.37, -6, 33, 22, 9, 5),
    "chicago": Climate("IL", 41.78, -87.75, -6, 190, 11, 15, 5),
    "san_francisco": Climate("CA", 37.62, -122.40, -8, 2, 15, 3, 3),
}

LICENSE_TEXT = """MIT License

Copyright (c) 2026 Sustainable Urban Systems Lab

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def _weather_row(moment: datetime, climate: Climate) -> list:
    day = moment.timetuple().tm_yday
    hour = moment.hour + 0.5
    season = math.sin(2 * math.pi * (day - 110) / 365)
    diurnal = math.sin(2 * math.pi * (hour - 9) / 24)
    dry_bulb = climate.mean_temperature + climate.seasonal_amplitude * season + climate.diurnal_amplitude * diurnal
    dew_point = dry_bulb - 6.0
    humidity = 100 * math.exp(
        17.625 * dew_point / (243.04 + dew_point)
        - 17.625 * dry_bulb / (243.04 + dry_bulb)
    )
    latitude = math.radians(climate.latitude)
    declination = math.radians(23.44) * math.sin(2 * math.pi * (284 + day) / 365)
    hour_angle = math.radians(15 * (hour - 12))
    elevation_sine = max(
        0.0,
        math.sin(latitude) * math.sin(declination)
        + math.cos(latitude) * math.cos(declination) * math.cos(hour_angle),
    )
    extra_direct = 1361 * (1 + 0.033 * math.cos(2 * math.pi * day / 365))
    direct = (700 + 50 * season) if elevation_sine > 0 else 0.0
    diffuse = 100 * elevation_sine
    global_horizontal = direct * elevation_sine + diffuse
    infrared = 0.85 * 5.670374419e-8 * (dry_bulb + 273.15) ** 4
    pressure = 101325 * math.exp(-climate.elevation / 8434.5)
    wind_direction = 180 + 45 * math.sin(2 * math.pi * day / 365)
    wind_speed = 2.5 + math.sin(2 * math.pi * hour / 24)
    return [
        moment.year, moment.month, moment.day, moment.hour + 1, 60, "?" * 29,
        f"{dry_bulb:.3f}", f"{dew_point:.3f}", f"{min(100, max(1, humidity)):.3f}",
        f"{pressure:.1f}", f"{extra_direct * elevation_sine:.3f}", f"{extra_direct:.3f}",
        f"{infrared:.3f}", f"{global_horizontal:.3f}", f"{direct:.3f}", f"{diffuse:.3f}",
        f"{110 * global_horizontal:.1f}", f"{100 * direct:.1f}", f"{120 * diffuse:.1f}",
        f"{20 * diffuse:.1f}", f"{wind_direction:.1f}", f"{wind_speed:.3f}",
        4, 4, 40, 77777, 9, 999999999, 15, 0.1, 0, 88, 0.2, 0, 1,
    ]


def write_epw(city: str, output_dir: str | Path, *, year: int = 2017) -> Path:
    """Write one explicitly synthetic file to a directory, using its own name."""
    if city not in CLIMATES:
        raise ValueError(f"Unknown synthetic climate {city!r}; choose one of {tuple(CLIMATES)}")
    if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
        raise ValueError("year must be a calendar year between 1 and 9999")
    if calendar.isleap(year):
        raise ValueError("Synthetic CI fixtures require a non-leap year (8760 records)")
    climate = CLIMATES[city]
    destination = Path(output_dir).expanduser().resolve() / f"synthetic_{city}.epw"
    destination.parent.mkdir(parents=True, exist_ok=True)
    (destination.parent / "SYNTHETIC-CI-LICENSE.txt").write_text(LICENSE_TEXT, encoding="ascii")
    start = datetime(year, 1, 1)
    day_name = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[start.weekday()]
    with destination.open("w", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerows([
            ["LOCATION", f"SYNTHETIC-CI_{city}", climate.state, "USA", "SYNTHETIC-CI_ANALYTIC", "000000",
             climate.latitude, climate.longitude, climate.time_zone, climate.elevation],
            ["DESIGN CONDITIONS", 0],
            ["TYPICAL/EXTREME PERIODS", 0],
            ["GROUND TEMPERATURES", 0],
            ["HOLIDAYS/DAYLIGHT SAVINGS", "No", 0, 0, 0],
            ["COMMENTS 1", "SYNTHETIC-CI: independently generated analytic test inputs; Copyright 2026 Sustainable Urban Systems Lab; MIT License; see SYNTHETIC-CI-LICENSE.txt"],
            ["COMMENTS 2", "CI PARITY ONLY: not TMY/IWEC; not measured or canonical benchmark weather; generated by tools/synthetic_weather.py"],
            ["DATA PERIODS", 1, 1, "SYNTHETIC-CI", day_name, "1/1", "12/31"],
        ])
        writer.writerows(_weather_row(start + timedelta(hours=index), climate) for index in range(8760))
    return destination


def generate_weather_files(output_dir: str | Path, *, year: int = 2017) -> dict[str, Path]:
    """Create all four analytic climates, preserving explicit synthetic names."""
    return {city: write_epw(city, output_dir, year=year) for city in CLIMATES}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--year", type=int, default=2017, help="Non-leap calendar year; default 2017")
    args = parser.parse_args(argv)
    files = generate_weather_files(args.output_dir, year=args.year)
    print(json.dumps({"kind": "SYNTHETIC-CI", "canonical_benchmark_weather": False,
                      "files": {city: str(path) for city, path in files.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
