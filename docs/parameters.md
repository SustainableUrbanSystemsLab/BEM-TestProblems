# Parameters and objectives

The objective callable takes physical parameter values in the order below.
Bounds are inclusive. Each symbol belongs to its problem family: `x1`, for
example, represents a different quantity in the office and school problems.
Inspect `problem.parameters`, `problem.bounds`, and `problem.objective_unit`
without installing or running EnergyPlus.

All objectives are minimized. The [objective structure guide](objective-structure.md)
gives their formulas and additive terms.

| Problems | Objective | Unit |
|---|---|---|
| 1–3 | Annual primary energy for heating, cooling, and lighting per floor area | kWh/(m² year) |
| 4–6 and 8 | Annual primary energy for heating, cooling, lighting, and fans per floor area | kWh/(m² year) |
| 9–10 | Source energy per floor area, including window-height penalties | MJ/m² |
| 13 | Combined energy, insulation, and radiator cost | EUR |

## Simple office: problems 1–3

The climates are Seattle, Houston, and Chicago, respectively. The shade
transmittance sets both the solar and visible transmittance of the exterior
shade; `0.2` means a transmitted fraction of 20%.

| Symbol | API name | Meaning | Unit | Bounds |
|---|---|---|---|---|
| `x1` | `orientation` | Building rotation (EnergyPlus north-axis angle) | ° | [-180, 180] |
| `x2` | `west_window_width` | West-facing window width | m | [0.1, 5.9] |
| `x3` | `east_window_width` | East-facing window width | m | [0.1, 5.9] |
| `x4` | `shade_transmittance` | Exterior-shade solar and visible transmittance | dimensionless | [0.2, 0.8] |

## Detailed office: problems 4–6 and 8

Problems 4–6 use Seattle, Houston, and Chicago, respectively. Problem 8 is the
reduced Chicago problem. Window widths are horizontal dimensions; overhang
depths describe the projection above the window. The shading setpoints are
incident-solar thresholds used by the exterior-shade controls. Night-cooling
setpoints are thermostat temperatures; supply temperature is a cooling-system
design input.

| Symbol | API name | Meaning | Unit | Bounds |
|---|---|---|---|---|
| `x1` | `north_window_width` | North window width | m | [1.224, 5.832] |
| `x2` | `west_window_width` | West window width | m | [7.344, 25.668] |
| `x3` | `east_window_width` | East window width | m | [7.344, 25.668] |
| `x4` | `south_window_width` | South window width | m | [1.224, 5.832] |
| `x5` | `west_overhang_depth` | West overhang depth | m | [0.05, 1.05] |
| `x6` | `east_overhang_depth` | East overhang depth | m | [0.05, 1.05] |
| `x7` | `south_overhang_depth` | South overhang depth | m | [0.05, 1.05] |
| `x8` | `west_shading_setpoint` | West shade solar threshold | W/m² | [100, 600] |
| `x9` | `east_shading_setpoint` | East shade solar threshold | W/m² | [100, 600] |
| `x10` | `south_shading_setpoint` | South shade solar threshold | W/m² | [100, 600] |
| `x11` | `summer_night_cooling_setpoint` | Summer night cooling temperature | °C | [20, 25] |
| `x12` | `winter_night_cooling_setpoint` | Winter night cooling temperature | °C | [20, 25] |
| `x13` | `cooling_supply_temperature` | Cooling design supply-air temperature | °C | [12, 18] |

**Problem 8:** physical `x11` is fixed at 25 °C and `x13` at 12 °C. Its
11-entry input vector contains `x1`–`x10`, followed by physical `x12`.
`problem.expanded_vector(x)` restores the full 13-entry physical order.

## Small and large offices: problems 9–10

Both use San Francisco weather. Window coordinates are the bottom and top
vertical positions in the template's base level; height equals top minus
bottom. Problem 10 repeats them at offsets of 16.7683 m and 33.5366 m for its
middle and upper represented levels.

| Symbol | API name | Meaning | Unit | Bounds |
|---|---|---|---|---|
| `x1` | `north_window_bottom` | North window bottom z coordinate | m | [0.8, 1.25] |
| `x2` | `north_window_top` | North window top z coordinate | m | [1.35, 2.2] |
| `x3` | `east_window_bottom` | East window bottom z coordinate | m | [0.8, 1.25] |
| `x4` | `east_window_top` | East window top z coordinate | m | [1.35, 2.2] |
| `x5` | `south_window_bottom` | South window bottom z coordinate | m | [0.8, 1.25] |
| `x6` | `south_window_top` | South window top z coordinate | m | [1.35, 2.2] |
| `x7` | `west_window_bottom` | West window bottom z coordinate | m | [0.8, 1.25] |
| `x8` | `west_window_top` | West window top z coordinate | m | [1.35, 2.2] |
| `x9` | `cooling_supply_temperature` | Cooling design supply-air temperature | °C | [12, 18] |
| `x10` | `weekday_heating_setback` | Weekday/Saturday off-hours heating temperature | °C | [13, 21] |
| `x11` | `holiday_heating_setback` | Sunday/holiday heating temperature | °C | [13, 21] |
| `x12` | `weekday_cooling_setback` | Weekday/Saturday off-hours cooling temperature | °C | [24, 36] |
| `x13` | `holiday_cooling_setback` | Sunday/holiday cooling temperature | °C | [24, 36] |

The API retains the original parameter names. The `weekday` settings also
apply during Saturday off-hours; the `holiday` settings apply all day on
Sundays, holidays, and the schedule's `AllOtherDays` category. Original
design-day schedule assignments are retained. The supply temperature also
determines a supply-air humidity ratio through the original linear formula.

In addition to these box bounds, the historical objective multiplies source
energy by `1 + 0.5*k`, where `k` counts façades whose window height is at most
0.5488 m. The paper prints 0.55 m; this implementation preserves the original
code's threshold. See the [objective structure guide](objective-structure.md)
for this discontinuous penalty.

## School: problem 13

This problem uses the included Belgrade winter design-day conditions. `UA`
means radiator thermal conductance: heat-transfer coefficient `U` times area
`A`, measured in W/K. Insulation thickness refers to the exterior mineral-wool
layer. Zone names follow the source model.

| Symbol | API name | Meaning | Unit | Bounds |
|---|---|---|---|---|
| `x1` | `insulation_thickness` | Exterior insulation thickness | m | [0.05, 0.3] |
| `x2` | `radiator_ua_class_zone_2` | Radiator UA: classroom zone 2 | W/K | [400, 800] |
| `x3` | `radiator_ua_work_zone` | Radiator UA: work zone | W/K | [60, 120] |
| `x4` | `radiator_ua_kitchen_zone` | Radiator UA: kitchen zone | W/K | [50, 110] |
| `x5` | `radiator_ua_music_zone` | Radiator UA: music zone | W/K | [80, 160] |
| `x6` | `radiator_ua_service_zone` | Radiator UA: service zone | W/K | [20, 50] |
| `x7` | `radiator_ua_washing_zone` | Radiator UA: washing zone | W/K | [80, 180] |
| `x8` | `radiator_ua_big_zone` | Radiator UA: large zone (BigZone) | W/K | [140, 280] |
| `x9` | `radiator_ua_class_zone_1` | Radiator UA: classroom zone 1 | W/K | [380, 760] |
| `x10` | `radiator_ua_office_zone` | Radiator UA: office zone | W/K | [350, 700] |

## Sources

The exact metadata are defined in [parameters.py](../src/bem_testproblems/parameters.py)
and [problems.py](../src/bem_testproblems/problems.py); model transformations are in
[models.py](../src/bem_testproblems/models.py). The [references](references.md)
identify Waibel, Wortmann, Evins, and Carmeliet (2019) and each originating
study. Upstream credit and license terms are retained in the
[third-party notices](../THIRD_PARTY_NOTICES.md).

Bounds describe the search domain. Simulation validity is checked separately;
see the [warmup diagnostics guide](warmup-diagnostics.md).
