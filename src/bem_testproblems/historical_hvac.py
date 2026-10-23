# SPDX-License-Identifier: MIT
"""Explicit 8.5 HVAC compatibility for the modern Chicago office models.

The coefficients and sizing rule come from EnergyPlus 8.5, not fitted results.
Other 26.2 physics and sizing behavior still apply; whole-engine parity is not
claimed. Canonical models and the completed campaign are unchanged.
"""

from .model_controls import WARMUP_CONVECTION, correct_v3_modern, corrected_v3_provenance

HISTORICAL_HVAC_PROBLEMS = (6, 8)
SOURCE = "https://github.com/NatLabRockies/EnergyPlus/blob/v8.5.0/src/EnergyPlus/"


def historical_hvac_provenance(number):
    if number not in HISTORICAL_HVAC_PROBLEMS:
        raise ValueError("Historical HVAC compatibility is available only for P6 and P8")
    return {
        "name": "historical-hvac", "physical_model_changes": True,
        "base_variant": "model-corrected-v3" if number == 6 else None,
        "base_recipe": corrected_v3_provenance(6) if number == 6 else None,
        "8.5.0": "Base input bytes unchanged",
        "26.2.0": "8.5 ceiling-diffuser equations and fan sizing rule through EMS",
        "convection": {"floor": [3.873, 0.082, 0.98], "ceiling": [2.234, 4.099, 0.503],
                       "wall": [1.208, 1.012, 0.604], "form": "a + b * ACH**c",
                       "sizing_ach": 0, "maximum_ach": 100, "minimum_mass_flow_kg_s": .01},
        "fan_sizing": "max(system heating design volume flow, system cooling design volume flow)",
        "sources": [SOURCE + "ConvectionCoefficients.cc#L3941-L4030",
                    SOURCE + "ConvectionCoefficients.cc#L7632-L7760",
                    SOURCE + "SimAirServingZones.cc#L5432"],
        "historical_equivalence": "Selected equations only; whole-engine equivalence not claimed",
        "preserved": "Weather, geometry, decision bounds, objective equation and strict diagnostics",
    }


def apply_historical_hvac(model, number):
    """Apply the opt-in variant to a freshly rendered canonical 26.2 model."""
    historical_hvac_provenance(number)
    if (len(model.get("SizingPeriod:DesignDay", {})) != 2
            or model.get("SizingPeriod:WeatherFileDays")
            or model.get("SizingPeriod:WeatherFileConditionType") or model.get("ZoneGroup")
            or len(model.get("Fan:VariableVolume", {})) != 2):
        raise ValueError("Historical HVAC requires the canonical Chicago sizing configuration")
    if any(obj["algorithm"] != "CeilingDiffuser"
           for obj in model["SurfaceConvectionAlgorithm:Inside"].values()):
        raise ValueError("Historical HVAC requires the canonical CeilingDiffuser model")
    if any(kind.startswith("EnergyManagementSystem:") for kind in model):
        raise ValueError("Historical HVAC requires canonical inputs without existing EMS controls")
    if number == 6:
        correct_v3_modern(model, 6)
    # The replacement program retains P6's weather-warmup initialization.
    for kind in list(model):
        if kind.startswith("EnergyManagementSystem:"):
            del model[kind]

    parents = model["BuildingSurface:Detailed"]
    surfaces = {**parents, **model["FenestrationSurface:Detailed"]}
    nodes = {obj["zone_name"]: obj["zone_air_node_name"]
             for obj in model["ZoneHVAC:EquipmentConnections"].values()}
    zones = {name: i for i, name in enumerate(sorted(model["Zone"]))}
    sensors = {"HistoricalPressure": {
        "output_variable_or_output_meter_index_key_name": "Environment",
        "output_variable_or_output_meter_name": "Site Outdoor Air Barometric Pressure"}}
    actuators, lines = {}, []
    for zone, index in zones.items():
        obj = model["Zone"][zone]
        multiplier, volume = obj.get("multiplier", 1), obj["volume"]
        if not isinstance(volume, (int, float)) or volume <= 0 or multiplier <= 0:
            raise ValueError("Historical HVAC requires positive explicit zone volumes and multipliers")
        for suffix, variable in (("Mass", "System Node Mass Flow Rate"),
                                 ("Temp", "System Node Temperature")):
            sensors[f"Historical{suffix}{index}"] = {
                "output_variable_or_output_meter_index_key_name": nodes[zone],
                "output_variable_or_output_meter_name": variable}
        lines += [f"SET HistoricalACH{index} = 0",
                  f"SET HistoricalM = HistoricalMass{index} / {multiplier}",
                  "IF CurrentEnvironment > 2 && HistoricalM >= 0.01",
                  f"SET HistoricalW = @WFnTdpPb HistoricalTemp{index} HistoricalPressure",
                  f"SET HistoricalRho = @RhoAirFnPbTdbW HistoricalPressure HistoricalTemp{index} HistoricalW",
                  f"SET HistoricalACH{index} = HistoricalM / HistoricalRho / {volume} * 3600",
                  f"SET HistoricalACH{index} = @Min HistoricalACH{index} 100",
                  f"SET HistoricalACH{index} = @Max HistoricalACH{index} 0", "ENDIF",
                  f"SET HistoricalFloor{index} = 3.873 + 0.082 * (HistoricalACH{index} ^ 0.98)",
                  f"SET HistoricalCeiling{index} = 2.234 + 4.099 * (HistoricalACH{index} ^ 0.503)",
                  f"SET HistoricalWall{index} = 1.208 + 1.012 * (HistoricalACH{index} ^ 0.604)"]
    for index, (name, surface) in enumerate(sorted(surfaces.items())):
        zone = surface.get("zone_name") or parents[surface["building_surface_name"]]["zone_name"]
        kind = surface["surface_type"].lower()
        category = "Floor" if kind == "floor" else "Ceiling" if kind in ("roof", "ceiling") else "Wall"
        actuator = f"HistoricalH{index:03}"
        actuators[actuator] = {
            "actuated_component_unique_name": name, "actuated_component_type": "Surface",
            "actuated_component_control_type": "Interior Surface Convection Heat Transfer Coefficient"}
        lines.append(f"SET {actuator} = Historical{category}{zones[zone]}")
    if number == 6:
        lines += ["IF CurrentEnvironment > 2 && WarmupFlag == 1"]
        lines += [f"SET {name} = {WARMUP_CONVECTION}" for name in actuators] + ["ENDIF"]
    model["EnergyManagementSystem:Sensor"] = sensors
    model["EnergyManagementSystem:Actuator"] = actuators
    model["EnergyManagementSystem:Program"] = {
        "HistoricalSizingConvection": {"lines": [{"program_line": s} for s in lines]}}
    model["EnergyManagementSystem:ProgramCallingManager"] = {
        f"HistoricalSizing{index}": {"energyplus_model_calling_point": hook,
                                    "programs": [{"program_name": "HistoricalSizingConvection"}]}
        for index, hook in enumerate(("BeginZoneTimestepBeforeInitHeatBalance", "BeginTimestepBeforePredictor",
                                      "AfterNewEnvironmentWarmUpIsComplete"))}
    model["EnergyManagementSystem:ProgramCallingManager"]["HistoricalHVAC"] = {
        "energyplus_model_calling_point": "InsideHVACSystemIterationLoop",
        "programs": [{"program_name": "HistoricalSizingConvection"}]}
    _restore_fan_sizing(model)


def _restore_fan_sizing(model):
    model["EnergyManagementSystem:InternalVariable"] = {
        "HistoricalHeatFlow": {"internal_data_index_key_name": "VAV Sys 1",
                               "internal_data_type": "Intermediate Air System Heating Volume Flow Rate"},
        "HistoricalCoolFlow": {"internal_data_index_key_name": "VAV Sys 1",
                               "internal_data_type": "Intermediate Air System Cooling Volume Flow Rate"}}
    lines = ["SET HistoricalMainFlow = @Max HistoricalHeatFlow HistoricalCoolFlow"]
    for index, name in enumerate(model["Fan:VariableVolume"]):
        actuator = f"HistoricalFanSize{index}"
        model["EnergyManagementSystem:Actuator"][actuator] = {
            "actuated_component_unique_name": name, "actuated_component_type": "Fan",
            "actuated_component_control_type": "Fan Autosized Air Flow Rate"}
        lines.append(f"SET {actuator} = HistoricalMainFlow")
    model["EnergyManagementSystem:Actuator"]["HistoricalLoopSize"] = {
        "actuated_component_unique_name": "VAV Sys 1", "actuated_component_type": "Sizing:System",
        "actuated_component_control_type": "Main Supply Volume Flow Rate"}
    lines.append("SET HistoricalLoopSize = HistoricalMainFlow")
    model["EnergyManagementSystem:Program"]["HistoricalAirflowRule"] = {
        "lines": [{"program_line": s} for s in lines]}
    model["EnergyManagementSystem:ProgramCallingManager"]["HistoricalAirflowRule"] = {
        "energyplus_model_calling_point": "EndOfSystemSizing",
        "programs": [{"program_name": "HistoricalAirflowRule"}]}
