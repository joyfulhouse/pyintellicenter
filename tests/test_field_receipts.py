"""Local ingestion provenance; these synthetic frames are not device evidence."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyintellicenter import ICBaseController, ICModelController, PoolModel


@pytest.fixture
def controller():
    model = PoolModel({"CIRCUIT": {"STATUS", "FREEZE"}})
    model.add_object("C1", {"OBJTYP": "CIRCUIT", "STATUS": "OFF", "FREEZE": "ON"})
    controller = ICModelController("192.0.2.1", model)
    controller._connection = MagicMock(connected=True)
    controller._connection.disconnect = AsyncMock()
    controller._monitor_paused = True
    return controller


def test_only_received_fields_refresh_even_without_value_changes(controller):
    assert controller.field_receipt("C1", "STATUS") is None
    callback = MagicMock()
    controller.set_updated_callback(callback)
    with patch("pyintellicenter.controller.time.monotonic", return_value=100):
        assert controller._apply_updates([{"objnam": "C1", "params": {"STATUS": "OFF"}}]) == {}
    callback.assert_not_called()
    with patch("pyintellicenter.controller.time.monotonic", return_value=105):
        receipt = controller.field_receipt("C1", "STATUS")
        assert receipt == {
            "age_seconds": 5,
            "connection_generation": 0,
            "current_connection": False,
        }
    assert controller.field_receipt("C1", "FREEZE") is None
    controller.model["C1"].update({"FREEZE": "OFF"})
    assert controller.field_receipt("C1", "FREEZE") is None
    receipt["connection_generation"] = 999
    assert controller.field_receipt("C1", "STATUS")["connection_generation"] == 0


async def test_reconnect_omissions_and_disconnect(controller):
    """Surviving cached values must not inherit receipts from the old socket."""
    controller.get_all_objects = AsyncMock(
        return_value=[{"objnam": "C1", "params": {"OBJTYP": "CIRCUIT"}}]
    )
    controller.send_cmd = AsyncMock(
        return_value={"objectList": [{"objnam": "C1", "params": {"STATUS": "OFF"}}]}
    )
    with patch.object(ICBaseController, "start", new_callable=AsyncMock):
        await controller.start()
        assert controller.field_receipt("C1", "OBJTYP")["current_connection"] is True
        assert controller.field_receipt("C1", "STATUS")["connection_generation"] == 1
        assert controller.field_receipt("C1", "FREEZE") is None
        controller._apply_updates([{"objnam": "C1", "params": {"FREEZE": "ON"}}])
        assert controller.field_receipt("C1", "FREEZE") is not None
        await controller.start()
    assert controller.model["C1"]["FREEZE"] == "ON"
    assert controller.field_receipt("C1", "FREEZE") is None
    assert controller.field_receipt("C1", "STATUS")["connection_generation"] == 2
    controller._connection.connected = False
    assert controller.field_receipt("C1", "STATUS")["current_connection"] is False
    await controller.stop()
    assert controller.field_receipt("C1", "STATUS")["current_connection"] is False


async def test_failed_start_does_not_reuse_receipts(controller):
    controller._apply_updates([{"objnam": "C1", "params": {"FREEZE": "ON"}}])
    with (
        patch.object(ICBaseController, "start", side_effect=OSError("unavailable")),
        pytest.raises(OSError),
    ):
        await controller.start()
    assert controller.field_receipt("C1", "FREEZE") is None


def test_removal_readdition_and_rejected_entries(controller):
    controller._apply_updates([{"objnam": "C1", "params": {"FREEZE": "ON"}}])
    controller.model.remove_object("C1")
    assert controller.field_receipt("C1", "FREEZE") is None
    controller.model.add_object("C1", {"OBJTYP": "CIRCUIT"})
    assert controller.field_receipt("C1", "FREEZE") is None
    controller._apply_updates(
        [
            {"objnam": "C1", "params": {"STATUS": None}},
            {"objnam": "UNKNOWN", "params": {"STATUS": "ON"}},
            {"objnam": "FILTERED", "params": {"OBJTYP": "UNSUPPORTED"}},
            {"objnam": "C1", "params": []},
            {"objnam": [], "params": {}},
            {},
            None,
        ]
    )
    assert controller.field_receipt("C1", "STATUS") is not None
    assert controller.field_receipt("C1", "FREEZE") is None
    assert controller.field_receipt("UNKNOWN", "STATUS") is None
    assert controller.field_receipt("FILTERED", "OBJTYP") is None


async def test_partial_initialization_and_snapshot_receipts(controller):
    controller.get_all_objects = AsyncMock(
        return_value=[{"objnam": "C1", "params": {"OBJTYP": "CIRCUIT", "STATUS": "OFF"}}]
    )
    controller.send_cmd = AsyncMock(side_effect=OSError("subscription failed"))
    controller._connection.disconnect = AsyncMock()
    with (
        patch.object(ICBaseController, "start", new_callable=AsyncMock),
        pytest.raises(OSError),
    ):
        await controller.start()
    assert controller.field_receipt("C1", "STATUS")["current_connection"] is False
    assert controller.field_receipt("C1", "FREEZE") is None


async def test_acknowledgement_does_not_create_receipt(controller):
    controller.send_cmd = AsyncMock(return_value={"response": "200"})
    await controller.set_circuit_state("C1", True)
    controller.send_cmd.assert_awaited_once()
    assert controller.field_receipt("C1", "STATUS") is None
    assert controller.model["C1"]["STATUS"] == "OFF"


async def test_old_transport_receipt_during_base_start_is_discarded(controller):
    async def close_old_and_connect():
        controller._apply_updates([{"objnam": "C1", "params": {"FREEZE": "ON"}}])
        assert controller.field_receipt("C1", "FREEZE")["current_connection"] is False

    controller.get_all_objects = AsyncMock(
        return_value=[{"objnam": "C1", "params": {"OBJTYP": "CIRCUIT"}}]
    )
    controller.send_cmd = AsyncMock(return_value={"objectList": []})
    with patch.object(ICBaseController, "start", side_effect=close_old_and_connect):
        await controller.start()
    assert controller.field_receipt("C1", "FREEZE") is None
    assert controller.field_receipt("C1", "OBJTYP")["current_connection"] is True


def test_receipt_recorded_before_value_change_callback(controller):
    observations = []
    controller.set_updated_callback(
        lambda ctrl, updates: observations.append(ctrl.field_receipt("C1", "STATUS"))
    )
    controller._apply_updates([{"objnam": "C1", "params": {"STATUS": "ON"}}])
    assert len(observations) == 1
    assert observations[0] is not None
