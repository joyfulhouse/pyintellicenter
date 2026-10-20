"""Cached eligibility remains distinct from fresh readiness and completion."""

from dataclasses import FrozenInstanceError

import pytest

from pyintellicenter import (
    ICError,
    ICLightGroupCapabilityError,
    LightGroupAction,
)
from pyintellicenter import (
    LightGroupCapabilityReason as Reason,
)
from tests.test_light_group_sync import make_controller, make_projection


@pytest.mark.parametrize("transport", ["tcp", "websocket"])
async def test_per_action_decisions_preserve_hardware_limits(transport: str) -> None:
    controller, connection = make_controller()
    controller._transport = transport
    caps = controller.get_light_group_capabilities("GROUP")
    assert caps.validated_actions == {LightGroupAction.SYNC}
    assert caps.for_action("SYNC").reason == Reason.VALIDATED
    assert caps.for_action("SET").reason == Reason.SET_PERSISTED_FLAGS
    assert caps.for_action("SWIM").reason == (
        Reason.SWIM_LATE_MIXED_STATE if transport == "tcp" else Reason.SWIM_PERSISTED_FLAGS
    )
    assert not caps.for_action("SWIM").supported
    assert connection.calls == []
    with pytest.raises(FrozenInstanceError):
        caps.decisions = ()  # type: ignore[misc]
    with pytest.raises(ValueError):
        caps.for_action("ACT")


@pytest.mark.parametrize("firmware", ["", "3.008", "1.064 ", "IC: 1.064"])
async def test_cached_rejection_has_same_reason_as_writer(firmware: str) -> None:
    controller, connection = make_controller(firmware=firmware)
    caps = controller.get_light_group_capabilities("GROUP")
    assert not caps.validated_actions
    assert {decision.reason for decision in caps.decisions} == {Reason.UNSUPPORTED_FIRMWARE}
    with pytest.raises(ICLightGroupCapabilityError) as raised:
        await controller.run_light_group_sync("GROUP")
    assert raised.value.reason == caps.for_action("SYNC").reason
    assert isinstance(raised.value, (ICError, ValueError))
    assert connection.calls == []


@pytest.mark.parametrize(
    ("name", "params", "reason"),
    [
        ("GROUP", {"SUBTYP": "CIRCGRP"}, Reason.UNSUPPORTED_PARENT),
        ("ROW_A", {"CIRCUIT": "MISSING"}, Reason.UNSUPPORTED_CHILD),
        ("ROW_A", {"CIRCUIT": "CHILD_B"}, Reason.DUPLICATE_CHILD),
        ("ROW_A", {"LISTORD": "00000"}, Reason.MALFORMED_MEMBERSHIP),
        ("ROW_A", {"PARENT": "MISSING"}, Reason.MEMBERSHIP_COUNT),
        ("OTHER_ROW", {"CIRCUIT": None}, Reason.INCOMPLETE_INVENTORY),
        ("AUX", {"PARENT": []}, Reason.MALFORMED_CACHE),
    ],
)
async def test_discovery_fails_closed_for_incomplete_cached_inventory(
    name: str, params: dict, reason: Reason
) -> None:
    controller, connection = make_controller()
    controller._model[name].update(params)
    caps = controller.get_light_group_capabilities("GROUP")
    assert not caps.validated_actions
    assert caps.for_action("SYNC").reason == reason
    with pytest.raises(ICLightGroupCapabilityError) as raised:
        await controller.run_light_group_sync("GROUP")
    assert raised.value.reason == reason
    assert connection.calls == []


async def test_unknown_transport_rejects_before_io() -> None:
    controller, connection = make_controller()
    controller._transport = "cloud"
    assert (
        controller.get_light_group_capabilities("GROUP").for_action("SYNC").reason
        == Reason.UNSUPPORTED_TRANSPORT
    )
    with pytest.raises(ICLightGroupCapabilityError, match="transport"):
        await controller.run_light_group_sync("GROUP")
    assert connection.calls == []


async def test_cached_eligibility_does_not_skip_fresh_preflight() -> None:
    controller, connection = make_controller()
    assert controller.get_light_group_capabilities("GROUP").for_action("SYNC").supported
    changed = make_projection("OFF")
    changed["objectList"][0]["params"]["SERVICE"] = "SERVICE"
    connection.projections[0] = changed
    with pytest.raises(ICError, match="mandatory SERVICE"):
        await controller.run_light_group_sync("GROUP")
    assert [call.command for call in connection.calls] == ["GetParamList"]
