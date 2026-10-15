"""Check the narrowly scoped normalization needed by the official transition."""

import pytest

from tools.transition_models import normalize_setpoint_manager_names


def test_duplicate_cross_type_manager_name_changes_only_mixedair_identifier():
    source = """SetpointManager:Scheduled,
  Shared Name, ! name
  Temperature,
  Schedule,
  Scheduled Node;
SetpointManager:MixedAir,
  Shared Name, ! name
  Temperature,
  Reference Node,
  Fan Inlet,
  Fan Outlet,
  MixedAir Node;
"""
    actual, changes = normalize_setpoint_manager_names(source)
    assert actual == source.replace("SetpointManager:MixedAir,\n  Shared Name,", "SetpointManager:MixedAir,\n  Shared Name__MixedAir,")
    assert changes[0]["old_name"] == "Shared Name"
    assert changes[0]["new_name"] == "Shared Name__MixedAir"
    assert normalize_setpoint_manager_names(actual) == (actual, [])


def test_referenced_duplicate_manager_name_requires_manual_review():
    source = "SetpointManager:Scheduled,\n  Shared,\n  Temperature;\nSetpointManager:MixedAir,\n  Shared,\n  Temperature;\nOther:Object, Shared;\n"
    with pytest.raises(ValueError, match="manual review"):
        normalize_setpoint_manager_names(source)
