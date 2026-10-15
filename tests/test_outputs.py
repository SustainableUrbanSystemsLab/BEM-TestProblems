"""Semantic extraction tests guard the original quantities and unit conversions."""


import pytest

from bem_testproblems.energyplus import RunResult
from bem_testproblems.outputs import OutputError, extract_outputs


def eso_run(tmp_path, variables, *, version="8.5.0", reverse=False):
    dictionary, records = [], []
    for report_id, (key, name, unit, frequency, value) in enumerate(variables, 10):
        dictionary.append(f"{report_id},11,{key},{name} [{unit}] !{frequency} [Value,Min,Max]")
        records.append(f"{report_id},{value},0,999999999")
    if reverse:
        dictionary.reverse()
        records.reverse()
    text = "Program Version,EnergyPlus\n" + "\n".join(dictionary) + "\nEnd of Data Dictionary\n" + "\n".join(records) + "\nEnd of Data\n"
    (tmp_path / "eplusout.eso").write_text(text)
    return RunResult(tmp_path, version)


def test_simple_uses_names_not_dictionary_order(tmp_path):
    run = eso_run(tmp_path, [
        ("ZONE ONE", "Zone Lights Electricity Energy", "J", "RunPeriod", 3.6e6),
        ("ZONE1AIR", "Zone Ideal Loads Supply Air Sensible Cooling Energy", "J", "RunPeriod", 7.2e6),
        ("ZONE1AIR", "Zone Ideal Loads Supply Air Sensible Heating Energy", "J", "RunPeriod", 10.8e6),
    ], version="26.2.0", reverse=True)
    assert extract_outputs("simple", run) == {"E_L": 1, "Q_c": 2, "Q_h": 3}


def test_school_rate_is_daily_average_not_maximum(tmp_path):
    run = eso_run(tmp_path, [
        ("HOTWATER", "District Heating Water Energy", "J", "Daily", 3.6e6),
        ("HOTWATER", "District Heating Water Rate", "W", "Daily", 24000),
    ], version="26.2.0")
    assert extract_outputs("school", run) == {"Q": 1, "P": 24}


def detailed_variables():
    variables = []
    for index, zone in enumerate(("NORTH", "WEST", "EAST", "SOUTH", "INTERIOR"), 1):
        variables.append((f"ZONE {zone} ZONE COIL", "Heating Coil Gas Energy", "J", "RunPeriod", index * 3.6e6))
        variables.append((f"ZONE {zone}", "Zone Lights Electric Energy", "J", "RunPeriod", index * 36e6))
    variables.extend([
        ("MAIN HEATING COIL 1", "Heating Coil Gas Energy", "J", "RunPeriod", 21.6e6),
        ("MAIN COOLING COIL 1", "Cooling Coil Electric Energy", "J", "RunPeriod", 25.2e6),
        ("SUPPLY FAN 1", "Fan Electric Energy", "J", "RunPeriod", 28.8e6),
        ("RETURN FAN 1", "Fan Electric Energy", "J", "RunPeriod", 32.4e6),
    ])
    return variables


def test_detailed_selects_supply_fan_without_adding_return(tmp_path):
    outputs = extract_outputs("detailed", eso_run(tmp_path, detailed_variables(), reverse=True))
    assert [outputs[f"H_{i}"] for i in range(1, 7)] == [1, 2, 3, 4, 5, 6]
    assert outputs["V_legacy"] == 8
    assert outputs["V_return"] == 9
    assert outputs["L_N"] == 10  # zone multiplier belongs to the outer loss


@pytest.mark.parametrize("unit,value", [("kWh", 1), ("J", "nan"), ("J", "inf")])
def test_wrong_units_and_nonfinite_values_fail(tmp_path, unit, value):
    run = eso_run(tmp_path, [
        ("ZONE ONE", "Zone Lights Electric Energy", unit, "RunPeriod", value),
        ("ZONE1AIR", "Zone Ideal Loads Supply Air Sensible Cooling Energy", "J", "RunPeriod", 1),
        ("ZONE1AIR", "Zone Ideal Loads Supply Air Sensible Heating Energy", "J", "RunPeriod", 1),
    ])
    with pytest.raises(OutputError):
        extract_outputs("simple", run)


def test_multiple_daily_records_are_not_silently_summed(tmp_path):
    run = eso_run(tmp_path, [
        ("HOTWATER", "District Heating Hot Water Energy", "J", "Daily", 3.6e6),
        ("HOTWATER", "District Heating Hot Water Rate", "W", "Daily", 1000),
    ])
    path = tmp_path / "eplusout.eso"
    path.write_text(path.read_text().replace("End of Data\n", "10,7200000\nEnd of Data\n"))
    with pytest.raises(OutputError, match="Expected one Daily value"):
        extract_outputs("school", run)


def test_office_preserves_displayed_conditioned_area_value(tmp_path):
    path = tmp_path / "eplustbl.csv"
    path.write_text("Ignored heading\n\nSite and Source Energy\n\n"
                    ",,Total Energy [GJ],Energy Per Total Building Area [MJ/m2],Energy Per Conditioned Building Area [MJ/m2]\n"
                    ",Total Source Energy,431.16,421.69,843.38\n")
    assert extract_outputs("office", RunResult(tmp_path, "8.5.0")) == {"Y": 843.38}
    path.write_text(path.read_text().replace("[MJ/m2]", "[kWh/m2]"))
    with pytest.raises(OutputError, match="MJ/m2"):
        extract_outputs("office", RunResult(tmp_path, "26.2.0"))


def test_missing_report_fails(tmp_path):
    with pytest.raises(OutputError, match="Missing"):
        extract_outputs("simple", RunResult(tmp_path, "8.5.0"))
