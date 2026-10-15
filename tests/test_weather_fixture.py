# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Validate independent synthetic weather structure and safe identity."""

import csv
import math
from datetime import datetime, timedelta

import pytest

from tools.synthetic_weather import CLIMATES, generate_weather_files, write_epw


@pytest.mark.parametrize("city", tuple(CLIMATES))
def test_synthetic_epw_is_complete_valid_and_explicitly_identified(city, tmp_path):
    path = write_epw(city, tmp_path)
    assert path.name == f"synthetic_{city}.epw"
    with path.open(encoding="ascii", newline="") as stream:
        rows = list(csv.reader(stream))
    assert len(rows) == 8760 + 8
    assert rows[0][1] == f"SYNTHETIC-CI_{city}"
    assert "MIT License" in rows[5][1]
    license_text = (path.parent / "SYNTHETIC-CI-LICENSE.txt").read_text(encoding="ascii")
    assert "Permission is hereby granted" in license_text
    assert "THE SOFTWARE IS PROVIDED" in license_text
    assert "not measured or canonical" in rows[6][1]
    assert rows[7] == ["DATA PERIODS", "1", "1", "SYNTHETIC-CI", "Sunday", "1/1", "12/31"]
    start = datetime(2017, 1, 1)
    solar_hours = 0
    for index, row in enumerate(rows[8:]):
        assert len(row) == 35
        moment = start + timedelta(hours=index)
        assert tuple(map(int, row[:5])) == (2017, moment.month, moment.day, moment.hour + 1, 60)
        numbers = [float(value) for value in row[6:]]
        assert all(math.isfinite(value) for value in numbers)
        dry, dew, rh, pressure = numbers[:4]
        assert -70 < dew <= dry < 70
        assert 0 < rh <= 100
        assert 31000 < pressure < 120000
        ghi, direct, diffuse = map(float, row[13:16])
        assert 0 <= diffuse <= ghi
        assert direct >= 0
        if direct == 0:
            assert ghi == diffuse == 0
        else:
            solar_hours += 1
        assert 0 <= float(row[20]) < 360
        assert 0 <= float(row[21]) < 40
    assert 3000 < solar_hours < 5500


def test_generator_is_deterministic_and_does_not_use_historical_names(tmp_path):
    first = generate_weather_files(tmp_path / "first")
    second = generate_weather_files(tmp_path / "second")
    assert set(first) == {"seattle", "houston", "chicago", "san_francisco"}
    for city in first:
        assert first[city].read_bytes() == second[city].read_bytes()
        assert first[city].name.startswith("synthetic_")
        assert not first[city].name.startswith(("USA_", "YUG_"))
    assert len({path.read_bytes() for path in first.values()}) == 4


def test_leap_year_is_rejected_before_creating_an_incomplete_fixture(tmp_path):
    with pytest.raises(ValueError, match="non-leap"):
        write_epw("chicago", tmp_path, year=2024)
    assert not list(tmp_path.iterdir())
