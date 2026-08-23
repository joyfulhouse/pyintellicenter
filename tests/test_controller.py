"""Tests for pyintellicenter controller module."""

import asyncio
import contextlib
import inspect
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyintellicenter import (
    ICBaseController,
    ICCommandError,
    ICConnectionError,
    ICConnectionHandler,
    ICConnectionMetrics,
    ICError,
    ICModelController,
    ICResponseError,
    ICSystemInfo,
    PoolModel,
)
from pyintellicenter.controller import prune


class TestPrune:
    """Test prune function."""

    def test_prune_dict_removes_undefined(self):
        """Test pruning removes key==value entries."""
        obj = {"key1": "value1", "key2": "key2", "key3": "value3"}
        result = prune(obj)

        assert result == {"key1": "value1", "key3": "value3"}
        assert "key2" not in result

    def test_prune_nested_dict(self):
        """Test pruning nested dictionaries."""
        obj = {"outer": {"inner1": "value1", "inner2": "inner2"}, "keep": "value"}
        result = prune(obj)

        assert result == {"outer": {"inner1": "value1"}, "keep": "value"}

    def test_prune_list(self):
        """Test pruning lists."""
        obj = [
            {"key1": "value1", "key2": "key2"},
            {"key3": "value3"},
        ]
        result = prune(obj)

        assert result == [{"key1": "value1"}, {"key3": "value3"}]

    def test_prune_primitives(self):
        """Test pruning primitive values."""
        assert prune("string") == "string"
        assert prune(42) == 42
        assert prune(None) is None


class TestICCommandError:
    """Test ICCommandError exception."""

    def test_init(self):
        """Test ICCommandError initialization."""
        error = ICCommandError("400")

        assert error.error_code == "400"
        assert "400" in str(error)

    def test_inheritance(self):
        """Test ICCommandError is an ICError."""
        error = ICCommandError("500")
        assert isinstance(error, ICError)
        assert isinstance(error, Exception)

    def test_repr(self):
        """Test repr representation."""
        error = ICCommandError("500")
        repr_str = repr(error)
        assert "ICCommandError" in repr_str
        assert "500" in repr_str


class TestICSystemInfo:
    """Test ICSystemInfo class."""

    def test_init(self):
        """Test ICSystemInfo initialization."""
        params = {
            "PROPNAME": "My Pool",
            "VER": "1.0.5",
            "MODE": "METRIC",
            "SNAME": "IntelliCenter",
        }
        info = ICSystemInfo("INCR", params)

        assert info.prop_name == "My Pool"
        assert info.sw_version == "1.0.5"
        assert info.uses_metric is True
        assert info.unique_id is not None
        assert len(info.unique_id) == 16  # blake2b with digest_size=8 produces 16 hex chars

    def test_uses_english(self):
        """Test system using English units."""
        params = {
            "PROPNAME": "My Pool",
            "VER": "1.0.5",
            "MODE": "ENGLISH",
            "SNAME": "IntelliCenter",
        }
        info = ICSystemInfo("INCR", params)

        assert info.uses_metric is False

    def test_update(self):
        """Test updating system info."""
        params = {
            "PROPNAME": "Pool 1",
            "VER": "1.0.0",
            "MODE": "METRIC",
            "SNAME": "IntelliCenter",
        }
        info = ICSystemInfo("INCR", params)

        info.update({"PROPNAME": "Pool 2", "VER": "1.0.1"})

        assert info.prop_name == "Pool 2"
        assert info.sw_version == "1.0.1"
        assert info.uses_metric is True

    def test_update_mode(self):
        """Test updating system mode."""
        params = {
            "PROPNAME": "Pool 1",
            "VER": "1.0.0",
            "MODE": "METRIC",
            "SNAME": "IntelliCenter",
        }
        info = ICSystemInfo("INCR", params)
        assert info.uses_metric is True

        info.update({"MODE": "ENGLISH"})

        assert info.uses_metric is False

    def test_objnam_property(self):
        """Test objnam property."""
        params = {
            "PROPNAME": "Pool 1",
            "VER": "1.0.0",
            "MODE": "METRIC",
            "SNAME": "IntelliCenter",
        }
        info = ICSystemInfo("SYS01", params)
        assert info.objnam == "SYS01"

    def test_unique_id_stable(self):
        """Test unique ID is stable for same system name."""
        params1 = {
            "PROPNAME": "Pool 1",
            "VER": "1.0.0",
            "MODE": "METRIC",
            "SNAME": "System1",
        }
        params2 = {
            "PROPNAME": "Pool 2",
            "VER": "2.0.0",
            "MODE": "ENGLISH",
            "SNAME": "System1",
        }

        info1 = ICSystemInfo("INCR", params1)
        info2 = ICSystemInfo("INCR", params2)

        # Same SNAME should produce same unique ID
        assert info1.unique_id == info2.unique_id

    def test_repr(self):
        """Test repr representation."""
        params = {
            "PROPNAME": "My Pool",
            "VER": "1.0.5",
            "MODE": "METRIC",
            "SNAME": "IntelliCenter",
        }
        info = ICSystemInfo("INCR", params)
        repr_str = repr(info)
        assert "ICSystemInfo" in repr_str
        assert "My Pool" in repr_str


class TestICConnectionMetrics:
    """Test ICConnectionMetrics dataclass."""

    def test_init_defaults(self):
        """Test ICConnectionMetrics default values."""
        metrics = ICConnectionMetrics()

        assert metrics.requests_sent == 0
        assert metrics.requests_completed == 0
        assert metrics.requests_failed == 0
        assert metrics.reconnect_attempts == 0
        assert metrics.successful_connects == 0

    def test_to_dict(self):
        """Test to_dict method."""
        metrics = ICConnectionMetrics()
        metrics.requests_sent = 100
        metrics.requests_completed = 95
        metrics.requests_failed = 3
        metrics.reconnect_attempts = 5
        metrics.successful_connects = 10

        result = metrics.to_dict()

        assert result["requests_sent"] == 100
        assert result["requests_completed"] == 95
        assert result["requests_failed"] == 3
        assert result["reconnect_attempts"] == 5
        assert result["successful_connects"] == 10

    def test_repr(self):
        """Test repr representation."""
        metrics = ICConnectionMetrics()
        metrics.requests_sent = 10
        repr_str = repr(metrics)
        assert "ICConnectionMetrics" in repr_str
        assert "10" in repr_str


class TestICBaseController:
    """Test ICBaseController class."""

    @pytest.fixture
    def controller(self):
        """Create a ICBaseController instance."""
        return ICBaseController("192.168.1.100", 6681)

    def test_init(self, controller):
        """Test ICBaseController initialization."""
        assert controller.host == "192.168.1.100"
        assert controller._port == 6681
        assert controller._connection is None
        assert controller._system_info is None

    def test_connected_false_when_no_connection(self, controller):
        """Test connected property when not connected."""
        assert controller.connected is False

    def test_metrics_property(self, controller):
        """Test metrics property."""
        assert controller.metrics is not None
        assert isinstance(controller.metrics, ICConnectionMetrics)

    def test_repr(self, controller):
        """Test repr representation."""
        repr_str = repr(controller)
        assert "ICBaseController" in repr_str
        assert "192.168.1.100" in repr_str

    @pytest.mark.asyncio
    async def test_start_creates_connection(self, controller):
        """Test start creates a connection and fetches system info."""
        mock_connection = AsyncMock()
        mock_connection.connected = True
        mock_connection.connect = AsyncMock()
        mock_connection.set_disconnect_callback = MagicMock()
        mock_connection.send_request = AsyncMock(
            return_value={
                "response": "200",
                "objectList": [
                    {
                        "objnam": "INCR",
                        "params": {
                            "PROPNAME": "Test Pool",
                            "VER": "1.0.0",
                            "MODE": "ENGLISH",
                            "SNAME": "TestSystem",
                        },
                    }
                ],
            }
        )

        with patch(
            "pyintellicenter.controller.ICConnection",
            return_value=mock_connection,
        ):
            await controller.start()

        assert controller.system_info is not None
        assert controller.system_info.prop_name == "Test Pool"
        assert controller.metrics.successful_connects == 1

    @pytest.mark.asyncio
    async def test_send_cmd_not_connected(self, controller):
        """Test send_cmd raises error when not connected."""
        with pytest.raises(ICConnectionError):
            await controller.send_cmd("GetParamList")

    @pytest.mark.asyncio
    async def test_send_cmd_success(self, controller):
        """Test send_cmd sends command and returns response."""
        mock_connection = AsyncMock()
        mock_connection.connected = True
        mock_connection.send_request = AsyncMock(return_value={"response": "200", "data": "test"})
        controller._connection = mock_connection

        result = await controller.send_cmd("GetParamList", {"condition": ""})

        assert result["response"] == "200"
        assert controller.metrics.requests_sent == 1
        assert controller.metrics.requests_completed == 1

    @pytest.mark.asyncio
    async def test_request_changes(self, controller):
        """Test request_changes sends SETPARAMLIST command."""
        mock_connection = AsyncMock()
        mock_connection.connected = True
        mock_connection.send_request = AsyncMock(return_value={"response": "200"})
        controller._connection = mock_connection

        await controller.request_changes("CIRCUIT1", {"STATUS": "ON"})

        mock_connection.send_request.assert_called_once()
        call_args = mock_connection.send_request.call_args
        assert call_args[0][0] == "SETPARAMLIST"

    @pytest.mark.asyncio
    async def test_stop(self, controller):
        """Test stop disconnects."""
        mock_connection = MagicMock()
        mock_connection.disconnect = AsyncMock()
        controller._connection = mock_connection

        await controller.stop()

        assert controller._connection is None


class TestICModelController:
    """Test ICModelController class."""

    @pytest.fixture
    def model(self):
        """Create a PoolModel instance."""
        return PoolModel()

    @pytest.fixture
    def controller(self, model):
        """Create a ICModelController instance."""
        return ICModelController("192.168.1.100", model, 6681)

    def test_init(self, controller, model):
        """Test ICModelController initialization."""
        assert controller.model is model
        assert controller._updated_callback is None

    def test_repr(self, controller):
        """Test repr representation."""
        repr_str = repr(controller)
        assert "ICModelController" in repr_str
        assert "192.168.1.100" in repr_str

    @pytest.mark.asyncio
    async def test_start_populates_model(self, controller, model):
        """Test start populates the model."""
        mock_connection = AsyncMock()
        mock_connection.connected = True
        mock_connection.connect = AsyncMock()
        mock_connection.set_disconnect_callback = MagicMock()
        mock_connection.set_notification_callback = MagicMock()
        mock_connection.send_request = AsyncMock(
            side_effect=[
                # System info response
                {
                    "response": "200",
                    "objectList": [
                        {
                            "objnam": "INCR",
                            "params": {
                                "PROPNAME": "Test Pool",
                                "VER": "1.0.0",
                                "MODE": "ENGLISH",
                                "SNAME": "TestSystem",
                            },
                        }
                    ],
                },
                # All objects response
                {
                    "response": "200",
                    "objectList": [
                        {
                            "objnam": "POOL1",
                            "params": {
                                "OBJTYP": "BODY",
                                "SUBTYP": "POOL",
                                "SNAME": "Pool",
                                "PARENT": "INCR",
                            },
                        }
                    ],
                },
                # RequestParamList response
                {
                    "response": "200",
                    "objectList": [{"objnam": "POOL1", "params": {"STATUS": "OFF"}}],
                },
            ]
        )

        with patch(
            "pyintellicenter.controller.ICConnection",
            return_value=mock_connection,
        ):
            await controller.start()

        assert model.num_objects >= 1

    def test_on_notification_updates_model(self, controller, model):
        """Test _on_notification updates the model."""
        # Add object to model
        model.add_object(
            "CIRCUIT1",
            {
                "OBJTYP": "CIRCUIT",
                "SUBTYP": "LIGHT",
                "SNAME": "Pool Light",
                "STATUS": "OFF",
            },
        )

        # Add system info
        params = {
            "PROPNAME": "Test Pool",
            "VER": "1.0.0",
            "MODE": "ENGLISH",
            "SNAME": "TestSystem",
        }
        controller._system_info = ICSystemInfo("SYS01", params)

        # Simulate notification
        msg = {
            "command": "NotifyList",
            "objectList": [{"objnam": "CIRCUIT1", "params": {"STATUS": "ON"}}],
        }
        controller._on_notification(msg)

        # Object should be updated
        obj = model["CIRCUIT1"]
        assert obj["STATUS"] == "ON"

    def test_on_notification_calls_callback(self, controller, model):
        """Test _on_notification calls update callback."""
        callback_called = False
        received_updates = None

        def update_callback(ctrl, updates):
            nonlocal callback_called, received_updates
            callback_called = True
            received_updates = updates

        controller.set_updated_callback(update_callback)

        # Add system info
        params = {
            "PROPNAME": "Test Pool",
            "VER": "1.0.0",
            "MODE": "ENGLISH",
            "SNAME": "TestSystem",
        }
        controller._system_info = ICSystemInfo("SYS01", params)

        # Add object to model
        model.add_object(
            "CIRCUIT1",
            {
                "OBJTYP": "CIRCUIT",
                "SUBTYP": "LIGHT",
                "SNAME": "Pool Light",
                "STATUS": "OFF",
            },
        )

        # Simulate notification
        msg = {
            "command": "NotifyList",
            "objectList": [{"objnam": "CIRCUIT1", "params": {"STATUS": "ON"}}],
        }
        controller._on_notification(msg)

        assert callback_called
        assert "CIRCUIT1" in received_updates

    def test_on_notification_adds_new_object_and_fires_callback(self, controller, model):
        """A NotifyList for a brand-new object adds it and fires the callback.

        Covers the zero-restart dynamic-object path (issue #42): an object not
        already in the model arrives via NotifyList with OBJTYP and is added,
        then surfaced through the existing updated callback. Called synchronously
        (no running loop) so the monitor re-request is skipped gracefully.
        """
        received_updates = {}

        def update_callback(ctrl, updates):
            received_updates.update(updates)

        controller.set_updated_callback(update_callback)

        assert model["CHM02"] is None

        msg = {
            "command": "NotifyList",
            "objectList": [
                {
                    "objnam": "CHM02",
                    "params": {
                        "OBJTYP": "CHEM",
                        "SUBTYP": "ICHEM",
                        "SNAME": "IntelliChem 2",
                        "STATUS": "ON",
                    },
                }
            ],
        }
        # No event loop running here; must not raise.
        controller._on_notification(msg)

        # Object added to the model and surfaced to the callback.
        new_obj = model["CHM02"]
        assert new_obj is not None
        assert new_obj.objtype == "CHEM"
        assert "CHM02" in received_updates
        assert received_updates["CHM02"]["STATUS"] == "ON"

    def test_on_notification_unknown_object_without_objtyp_no_crash(self, controller, model):
        """A NotifyList for an unknown objnam lacking OBJTYP is ignored safely."""
        callback_calls = []
        controller.set_updated_callback(lambda ctrl, updates: callback_calls.append(updates))

        msg = {
            "command": "NotifyList",
            "objectList": [{"objnam": "MYSTERY", "params": {"STATUS": "ON"}}],
        }
        controller._on_notification(msg)

        assert model["MYSTERY"] is None
        # Nothing changed, so the callback should not fire.
        assert callback_calls == []

    @pytest.mark.asyncio
    async def test_new_object_triggers_monitoring_request(self, controller, model):
        """A new object arriving via NotifyList triggers a RequestParamList.

        IntelliCenter does not push attributes for an object that was not part
        of the initial monitoring request, so the controller must (re-)subscribe
        the newly-added object. Runs inside an event loop so the background
        monitor task is scheduled.
        """
        sent_commands = []

        async def fake_send_cmd(cmd, extra=None):
            sent_commands.append((cmd, extra))
            return {"response": "200", "objectList": []}

        controller.send_cmd = AsyncMock(side_effect=fake_send_cmd)

        msg = {
            "command": "NotifyList",
            "objectList": [
                {
                    "objnam": "CHM02",
                    "params": {
                        "OBJTYP": "CHEM",
                        "SUBTYP": "ICHEM",
                        "SNAME": "IntelliChem 2",
                    },
                }
            ],
        }
        controller._on_notification(msg)

        # The monitor request runs as a background task; let it run.
        assert controller._monitor_tasks
        await asyncio.gather(*controller._monitor_tasks)

        # A RequestParamList was sent that targets the new object.
        request_param_calls = [extra for cmd, extra in sent_commands if cmd == "RequestParamList"]
        assert request_param_calls
        targeted = {item["objnam"] for extra in request_param_calls for item in extra["objectList"]}
        assert "CHM02" in targeted

    @pytest.mark.asyncio
    async def test_request_monitoring_for_handles_errors(self, controller, model):
        """_request_monitoring_for swallows connection errors (background task)."""
        model.add_object("CHM02", {"OBJTYP": "CHEM", "SUBTYP": "ICHEM", "SNAME": "IntelliChem 2"})
        controller.send_cmd = AsyncMock(side_effect=ICConnectionError("boom"))

        # Must not raise despite the failing send_cmd.
        await controller._request_monitoring_for({"CHM02"})

    @pytest.mark.asyncio
    async def test_request_monitoring_for_no_matching_objects(self, controller):
        """_request_monitoring_for is a no-op when nothing matches."""
        controller.send_cmd = AsyncMock()
        await controller._request_monitoring_for({"DOES_NOT_EXIST"})
        controller.send_cmd.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_monitoring_for_handles_malformed_response(self, controller, model):
        """A response missing/!list objectList is skipped, not crashed."""
        model.add_object("CHM02", {"OBJTYP": "CHEM", "SUBTYP": "ICHEM", "SNAME": "IntelliChem 2"})

        # Missing objectList entirely.
        controller.send_cmd = AsyncMock(return_value={"response": "200"})
        await controller._request_monitoring_for({"CHM02"})  # must not raise

        # objectList present but not a list.
        controller.send_cmd = AsyncMock(return_value={"objectList": "nope"})
        await controller._request_monitoring_for({"CHM02"})  # must not raise

    @pytest.mark.asyncio
    async def test_request_monitoring_for_respects_batch_limit(self, controller, monkeypatch):
        """No single RequestParamList batch exceeds MAX_ATTRIBUTES_PER_QUERY keys.

        Updated for issue #63: monitoring queries are now built directly from
        the model's attribute map (not by filtering attributes_to_track()), so
        the oversized tracking set is crafted through the map itself.
        """
        from pyintellicenter.controller import MAX_ATTRIBUTES_PER_QUERY

        # Craft a tracked type whose key count forces a split into batches
        # (5 objects x 20 keys = 100 > 50).
        monkeypatch.setattr(
            controller._model, "_attribute_map", {"CHEM": {f"K{j}" for j in range(20)}}
        )
        objnams = {f"OBJ{i}" for i in range(5)}
        for objnam in objnams:
            controller._model.add_object(objnam, {"OBJTYP": "CHEM", "SNAME": objnam})

        batches: list[list[dict]] = []

        async def fake_send_cmd(cmd, extra=None):
            if cmd == "RequestParamList":
                batches.append(extra["objectList"])
            return {"objectList": []}

        controller.send_cmd = AsyncMock(side_effect=fake_send_cmd)
        await controller._request_monitoring_for(objnams)

        assert len(batches) > 1, "expected the oversized query to split into batches"
        for batch in batches:
            total_keys = sum(len(item["keys"]) for item in batch)
            assert total_keys <= MAX_ATTRIBUTES_PER_QUERY
        # Every object is still covered exactly once across the batches.
        covered = [item["objnam"] for batch in batches for item in batch]
        assert sorted(covered) == sorted(objnams)

    @pytest.mark.asyncio
    async def test_request_monitoring_targets_only_new_objnams(self, controller, model):
        """Monitoring requests for new objects cover only the new objnams.

        Regression test for issue #63: the queries are built directly for the
        added objects; the whole-model attributes_to_track() walk is not used
        and pre-existing objects are not re-subscribed.
        """
        model.add_object("POOL1", {"OBJTYP": "BODY", "SUBTYP": "POOL", "SNAME": "Pool"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"})
        model.add_object("CHM02", {"OBJTYP": "CHEM", "SUBTYP": "ICHEM", "SNAME": "IntelliChem 2"})

        def fail_attributes_to_track():
            pytest.fail("attributes_to_track() must not be used for new-object monitoring")

        model.attributes_to_track = fail_attributes_to_track

        batches: list[list[dict]] = []

        async def fake_send_cmd(cmd, extra=None):
            if cmd == "RequestParamList":
                batches.append(extra["objectList"])
            return {"objectList": []}

        controller.send_cmd = AsyncMock(side_effect=fake_send_cmd)
        await controller._request_monitoring_for({"CHM02"})

        targeted = [item["objnam"] for batch in batches for item in batch]
        assert targeted == ["CHM02"]

    @pytest.mark.asyncio
    async def test_set_circuit_state(self, controller):
        """Test set_circuit_state convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_circuit_state("C001", True)

        controller._connection.send_request.assert_called_once()
        call_args = controller._connection.send_request.call_args
        assert call_args[0][0] == "SETPARAMLIST"
        assert call_args[1]["objectList"][0]["objnam"] == "C001"
        assert call_args[1]["objectList"][0]["params"]["STATUS"] == "ON"

    @pytest.mark.asyncio
    async def test_set_circuit_state_off(self, controller):
        """Test set_circuit_state with state=False."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_circuit_state("C001", False)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["params"]["STATUS"] == "OFF"

    @pytest.mark.asyncio
    async def test_set_heat_mode(self, controller):
        """Test set_heat_mode convenience method."""
        from pyintellicenter import HeaterType

        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_heat_mode("B001", HeaterType.HEATER)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["objnam"] == "B001"
        assert call_args[1]["objectList"][0]["params"]["MODE"] == "2"

    @pytest.mark.asyncio
    async def test_set_setpoint(self, controller):
        """Test set_setpoint convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_setpoint("B001", 85)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["objnam"] == "B001"
        assert call_args[1]["objectList"][0]["params"]["LOTMP"] == "85"

    @pytest.mark.asyncio
    async def test_set_super_chlorinate(self, controller):
        """Test set_super_chlorinate convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_super_chlorinate("CHEM01", True)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["objnam"] == "CHEM01"
        assert call_args[1]["objectList"][0]["params"]["SUPER"] == "ON"

    def test_get_bodies(self, controller, model):
        """Test get_bodies convenience method."""
        model.add_object("B001", {"OBJTYP": "BODY", "SUBTYP": "POOL", "SNAME": "Pool"})
        model.add_object("B002", {"OBJTYP": "BODY", "SUBTYP": "SPA", "SNAME": "Spa"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"})

        bodies = controller.get_bodies()

        assert len(bodies) == 2
        assert all(obj.objtype == "BODY" for obj in bodies)

    def test_get_circuits(self, controller, model):
        """Test get_circuits convenience method."""
        model.add_object("B001", {"OBJTYP": "BODY", "SUBTYP": "POOL", "SNAME": "Pool"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"})
        model.add_object("C002", {"OBJTYP": "CIRCUIT", "SUBTYP": "GENERIC", "SNAME": "Pump"})

        circuits = controller.get_circuits()

        assert len(circuits) == 2
        assert all(obj.objtype == "CIRCUIT" for obj in circuits)

    def test_get_heaters(self, controller, model):
        """Test get_heaters convenience method."""
        model.add_object("H001", {"OBJTYP": "HEATER", "SUBTYP": "GENERIC", "SNAME": "Heater"})
        model.add_object("H002", {"OBJTYP": "HEATER", "SUBTYP": "SOLAR", "SNAME": "Solar"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"})

        heaters = controller.get_heaters()

        assert len(heaters) == 2
        assert all(obj.objtype == "HEATER" for obj in heaters)

    def test_get_schedules(self, controller, model):
        """Test get_schedules convenience method."""
        model.add_object("S001", {"OBJTYP": "SCHED", "SUBTYP": "SCHED", "SNAME": "Schedule 1"})
        model.add_object("S002", {"OBJTYP": "SCHED", "SUBTYP": "SCHED", "SNAME": "Schedule 2"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"})

        schedules = controller.get_schedules()

        assert len(schedules) == 2
        assert all(obj.objtype == "SCHED" for obj in schedules)

    def test_get_sensors(self, controller, model):
        """Test get_sensors convenience method."""
        model.add_object("SENSE01", {"OBJTYP": "SENSE", "SUBTYP": "POOL", "SNAME": "Pool Temp"})
        model.add_object("SENSE02", {"OBJTYP": "SENSE", "SUBTYP": "AIR", "SNAME": "Air Temp"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"})

        sensors = controller.get_sensors()

        assert len(sensors) == 2
        assert all(obj.objtype == "SENSE" for obj in sensors)

    def test_get_pumps(self, controller, model):
        """Test get_pumps convenience method."""
        model.add_object("PUMP01", {"OBJTYP": "PUMP", "SUBTYP": "SPEED", "SNAME": "Main Pump"})
        model.add_object("PUMP02", {"OBJTYP": "PUMP", "SUBTYP": "VSF", "SNAME": "Booster"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"})

        pumps = controller.get_pumps()

        assert len(pumps) == 2
        assert all(obj.objtype == "PUMP" for obj in pumps)

    def test_get_chem_controllers(self, controller, model):
        """Test get_chem_controllers convenience method."""
        model.add_object("CHEM01", {"OBJTYP": "CHEM", "SUBTYP": "ICHLOR", "SNAME": "Salt Cell"})
        model.add_object("CHEM02", {"OBJTYP": "CHEM", "SUBTYP": "ICHEM", "SNAME": "IntelliChem"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"})

        chem = controller.get_chem_controllers()

        assert len(chem) == 2
        assert all(obj.objtype == "CHEM" for obj in chem)

    @pytest.mark.asyncio
    async def test_set_multiple_circuit_states(self, controller):
        """Test set_multiple_circuit_states convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_multiple_circuit_states(["C001", "C002", "C003"], True)

        controller._connection.send_request.assert_called_once()
        call_args = controller._connection.send_request.call_args
        assert call_args[0][0] == "SETPARAMLIST"
        object_list = call_args[1]["objectList"]
        assert len(object_list) == 3
        assert all(obj["params"]["STATUS"] == "ON" for obj in object_list)

    @pytest.mark.asyncio
    async def test_set_multiple_circuit_states_off(self, controller):
        """Test set_multiple_circuit_states with state=False."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_multiple_circuit_states(["C001", "C002"], False)

        call_args = controller._connection.send_request.call_args
        object_list = call_args[1]["objectList"]
        assert all(obj["params"]["STATUS"] == "OFF" for obj in object_list)

    @pytest.mark.asyncio
    async def test_get_configuration(self, controller):
        """Test get_configuration convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "answer": [{"type": "body", "name": "Pool"}]}
        )

        result = await controller.get_configuration()

        controller._connection.send_request.assert_called_once()
        call_args = controller._connection.send_request.call_args
        assert call_args[0][0] == "GetQuery"
        assert call_args[1]["queryName"] == "GetConfiguration"
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_hardware_definition(self, controller):
        """Test get_hardware_definition convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={
                "response": "200",
                "answer": [{"type": "panel", "children": [{"type": "body"}]}],
            }
        )

        result = await controller.get_hardware_definition()

        controller._connection.send_request.assert_called_once()
        call_args = controller._connection.send_request.call_args
        assert call_args[0][0] == "GetQuery"
        assert call_args[1]["queryName"] == "GetHardwareDefinition"
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_set_ph_setpoint(self, controller):
        """Test set_ph_setpoint convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_ph_setpoint("CHEM01", 7.4)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["objnam"] == "CHEM01"
        assert call_args[1]["objectList"][0]["params"]["PHSET"] == "7.4"

    @pytest.mark.asyncio
    async def test_set_ph_setpoint_invalid_range(self, controller):
        """Test set_ph_setpoint rejects invalid values."""
        controller._connection = MagicMock()
        controller._connection.connected = True

        with pytest.raises(ValueError, match="outside valid range"):
            await controller.set_ph_setpoint("CHEM01", 5.0)

        with pytest.raises(ValueError, match="outside valid range"):
            await controller.set_ph_setpoint("CHEM01", 9.0)

    @pytest.mark.asyncio
    async def test_set_ph_setpoint_invalid_step(self, controller):
        """Test set_ph_setpoint rejects non-0.1 increments."""
        controller._connection = MagicMock()
        controller._connection.connected = True

        # IntelliChem only accepts pH values in 0.1 increments
        with pytest.raises(ValueError, match="0.1 increments"):
            await controller.set_ph_setpoint("CHEM01", 7.45)

        with pytest.raises(ValueError, match="0.1 increments"):
            await controller.set_ph_setpoint("CHEM01", 7.05)

        with pytest.raises(ValueError, match="0.1 increments"):
            await controller.set_ph_setpoint("CHEM01", 7.123)

    @pytest.mark.asyncio
    async def test_set_ph_setpoint_rounds_to_one_decimal(self, controller):
        """Test set_ph_setpoint sends value rounded to one decimal place."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        # Value that's effectively 7.4 should work (floating point tolerance)
        await controller.set_ph_setpoint("CHEM01", 7.4000001)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["params"]["PHSET"] == "7.4"

    @pytest.mark.asyncio
    async def test_set_orp_setpoint(self, controller):
        """Test set_orp_setpoint convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_orp_setpoint("CHEM01", 700)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["objnam"] == "CHEM01"
        assert call_args[1]["objectList"][0]["params"]["ORPSET"] == "700"

    @pytest.mark.asyncio
    async def test_set_orp_setpoint_invalid_range(self, controller):
        """Test set_orp_setpoint rejects invalid values."""
        controller._connection = MagicMock()
        controller._connection.connected = True

        with pytest.raises(ValueError, match="outside valid range"):
            await controller.set_orp_setpoint("CHEM01", 100)

        with pytest.raises(ValueError, match="outside valid range"):
            await controller.set_orp_setpoint("CHEM01", 1000)

    @pytest.mark.asyncio
    async def test_set_chlorinator_output(self, controller):
        """Test set_chlorinator_output convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_chlorinator_output("CHEM01", 50, 100)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["objnam"] == "CHEM01"
        assert call_args[1]["objectList"][0]["params"]["PRIM"] == "50"
        assert call_args[1]["objectList"][0]["params"]["SEC"] == "100"

    @pytest.mark.asyncio
    async def test_set_chlorinator_output_primary_only(self, controller):
        """Test set_chlorinator_output with only primary percentage."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_chlorinator_output("CHEM01", 75)

        call_args = controller._connection.send_request.call_args
        params = call_args[1]["objectList"][0]["params"]
        assert params["PRIM"] == "75"
        assert "SEC" not in params

    @pytest.mark.asyncio
    async def test_set_chlorinator_output_invalid_range(self, controller):
        """Test set_chlorinator_output rejects invalid values."""
        controller._connection = MagicMock()
        controller._connection.connected = True

        with pytest.raises(ValueError, match="Primary percentage"):
            await controller.set_chlorinator_output("CHEM01", 150)

        with pytest.raises(ValueError, match="Secondary percentage"):
            await controller.set_chlorinator_output("CHEM01", 50, 150)

    def test_get_ph_setpoint(self, controller, model):
        """Test get_ph_setpoint getter method."""
        model.add_object(
            "CHEM01", {"OBJTYP": "CHEM", "SUBTYP": "ICHEM", "SNAME": "IntelliChem", "PHSET": "7.4"}
        )

        result = controller.get_ph_setpoint("CHEM01")
        assert result == 7.4

    def test_get_ph_setpoint_missing(self, controller, model):
        """Test get_ph_setpoint returns None when not set."""
        model.add_object("CHEM01", {"OBJTYP": "CHEM", "SUBTYP": "ICHEM", "SNAME": "IntelliChem"})

        result = controller.get_ph_setpoint("CHEM01")
        assert result is None

    def test_get_orp_setpoint(self, controller, model):
        """Test get_orp_setpoint getter method."""
        model.add_object(
            "CHEM01", {"OBJTYP": "CHEM", "SUBTYP": "ICHEM", "SNAME": "IntelliChem", "ORPSET": "700"}
        )

        result = controller.get_orp_setpoint("CHEM01")
        assert result == 700

    def test_get_chlorinator_output(self, controller, model):
        """Test get_chlorinator_output getter method."""
        model.add_object(
            "CHEM01",
            {
                "OBJTYP": "CHEM",
                "SUBTYP": "ICHLOR",
                "SNAME": "Salt Cell",
                "PRIM": "50",
                "SEC": "100",
            },
        )

        result = controller.get_chlorinator_output("CHEM01")
        assert result["primary"] == 50
        assert result["secondary"] == 100

    def test_get_valves(self, controller, model):
        """Test get_valves convenience method."""
        model.add_object("VAL01", {"OBJTYP": "VALVE", "SUBTYP": "LEGACY", "SNAME": "Valve 1"})
        model.add_object("VAL02", {"OBJTYP": "VALVE", "SUBTYP": "LEGACY", "SNAME": "Valve 2"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"})

        valves = controller.get_valves()

        assert len(valves) == 2
        assert all(obj.objtype == "VALVE" for obj in valves)

    def test_get_covers(self, controller, model):
        """Test get_covers convenience method."""
        model.add_object("CVR01", {"OBJTYP": "EXTINSTR", "SUBTYP": "COVER", "SNAME": "Pool Cover"})
        model.add_object("CVR02", {"OBJTYP": "EXTINSTR", "SUBTYP": "COVER", "SNAME": "Spa Cover"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"})

        covers = controller.get_covers()

        assert len(covers) == 2
        assert all(obj.objtype == "EXTINSTR" for obj in covers)
        assert all(obj.subtype == "COVER" for obj in covers)

    def test_get_covers_filters_by_subtype(self, controller, model):
        """Test that get_covers only returns COVER subtype, not other EXTINSTR."""
        model.add_object("CVR01", {"OBJTYP": "EXTINSTR", "SUBTYP": "COVER", "SNAME": "Pool Cover"})
        model.add_object(
            "EXT01", {"OBJTYP": "EXTINSTR", "SUBTYP": "OTHER", "SNAME": "Other Instrument"}
        )

        covers = controller.get_covers()

        assert len(covers) == 1
        assert covers[0].objnam == "CVR01"

    @pytest.mark.asyncio
    async def test_set_cover_state(self, controller, model):
        """Test set_cover_state drives POSIT (position), not STATUS (enabled)."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        model.add_object(
            "CVR01",
            {
                "OBJTYP": "EXTINSTR",
                "SUBTYP": "COVER",
                "SNAME": "Pool Cover",
                "STATUS": "ON",
                "POSIT": "OFF",
            },
        )

        await controller.set_cover_state("CVR01", True)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["objnam"] == "CVR01"
        assert call_args[1]["objectList"][0]["params"]["POSIT"] == "ON"

    @pytest.mark.asyncio
    async def test_set_cover_state_off(self, controller, model):
        """Test set_cover_state with state=False."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        model.add_object(
            "CVR01",
            {
                "OBJTYP": "EXTINSTR",
                "SUBTYP": "COVER",
                "SNAME": "Pool Cover",
                "STATUS": "ON",
                "POSIT": "ON",
            },
        )

        await controller.set_cover_state("CVR01", False)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["params"]["POSIT"] == "OFF"

    def test_is_cover_on(self, controller, model):
        """Test is_cover_on reads POSIT, independent of STATUS (enabled)."""
        model.add_object(
            "CVR01",
            {
                "OBJTYP": "EXTINSTR",
                "SUBTYP": "COVER",
                "SNAME": "Pool Cover",
                "STATUS": "ON",
                "POSIT": "ON",
            },
        )
        model.add_object(
            "CVR02",
            {
                "OBJTYP": "EXTINSTR",
                "SUBTYP": "COVER",
                "SNAME": "Spa Cover",
                "STATUS": "ON",
                "POSIT": "OFF",
            },
        )

        assert controller.is_cover_on("CVR01") is True
        assert controller.is_cover_on("CVR02") is False
        assert controller.is_cover_on("NONEXISTENT") is False

    def test_is_cover_enabled(self, controller, model):
        """Test is_cover_enabled reads STATUS, independent of POSIT (position).

        Confirmed against real panel traffic: toggling "Cover Enabled" in
        Settings > Covers sends a SETPARAMLIST writing STATUS and never
        touches POSIT.
        """
        model.add_object(
            "CVR01",
            {
                "OBJTYP": "EXTINSTR",
                "SUBTYP": "COVER",
                "SNAME": "Pool Cover",
                "STATUS": "ON",
                "POSIT": "OFF",
            },
        )
        model.add_object(
            "CVR02",
            {
                "OBJTYP": "EXTINSTR",
                "SUBTYP": "COVER",
                "SNAME": "Spa Cover",
                "STATUS": "OFF",
                "POSIT": "OFF",
            },
        )

        assert controller.is_cover_enabled("CVR01") is True
        assert controller.is_cover_enabled("CVR02") is False
        assert controller.is_cover_enabled("NONEXISTENT") is False

    @pytest.mark.asyncio
    async def test_set_vacation_mode(self, controller, model):
        """Test set_vacation_mode convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        # Setup system info
        params = {
            "PROPNAME": "Test Pool",
            "VER": "1.0.0",
            "MODE": "ENGLISH",
            "SNAME": "TestSystem",
        }
        controller._system_info = ICSystemInfo("SYS01", params)

        await controller.set_vacation_mode(True)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["objnam"] == "SYS01"
        assert call_args[1]["objectList"][0]["params"]["VACFLO"] == "ON"

    @pytest.mark.asyncio
    async def test_set_vacation_mode_off(self, controller, model):
        """Test set_vacation_mode with enabled=False."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        params = {
            "PROPNAME": "Test Pool",
            "VER": "1.0.0",
            "MODE": "ENGLISH",
            "SNAME": "TestSystem",
        }
        controller._system_info = ICSystemInfo("SYS01", params)

        await controller.set_vacation_mode(False)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["params"]["VACFLO"] == "OFF"

    @pytest.mark.asyncio
    async def test_set_vacation_mode_no_system_info(self, controller):
        """Test set_vacation_mode raises error when system info not available."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._system_info = None

        with pytest.raises(ICCommandError, match="System info not available"):
            await controller.set_vacation_mode(True)

    def test_is_vacation_mode(self, controller, model):
        """Test is_vacation_mode getter method."""
        params = {
            "PROPNAME": "Test Pool",
            "VER": "1.0.0",
            "MODE": "ENGLISH",
            "SNAME": "TestSystem",
        }
        controller._system_info = ICSystemInfo("SYS01", params)
        model.add_object("SYS01", {"OBJTYP": "SYSTEM", "SNAME": "System", "VACFLO": "ON"})

        assert controller.is_vacation_mode() is True

    def test_is_vacation_mode_false(self, controller, model):
        """Test is_vacation_mode returns False when disabled."""
        params = {
            "PROPNAME": "Test Pool",
            "VER": "1.0.0",
            "MODE": "ENGLISH",
            "SNAME": "TestSystem",
        }
        controller._system_info = ICSystemInfo("SYS01", params)
        model.add_object("SYS01", {"OBJTYP": "SYSTEM", "SNAME": "System", "VACFLO": "OFF"})

        assert controller.is_vacation_mode() is False

    def test_is_vacation_mode_no_system_info(self, controller):
        """Test is_vacation_mode returns False when system info not available."""
        controller._system_info = None
        assert controller.is_vacation_mode() is False

    def test_on_notification_ignores_non_notify_commands(self, controller, model):
        """Test _on_notification ignores non-NotifyList commands."""
        model.add_object(
            "CIRCUIT1",
            {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light", "STATUS": "OFF"},
        )

        # Simulate non-NotifyList message
        msg = {
            "command": "SomeOtherCommand",
            "objectList": [{"objnam": "CIRCUIT1", "params": {"STATUS": "ON"}}],
        }
        controller._on_notification(msg)

        # Object should NOT be updated
        obj = model["CIRCUIT1"]
        assert obj["STATUS"] == "OFF"

    def test_on_notification_handles_malformed_data(self, controller, model):
        """Test _on_notification handles malformed notification data gracefully."""
        # Add system info
        params = {
            "PROPNAME": "Test",
            "VER": "1.0.0",
            "MODE": "ENGLISH",
            "SNAME": "Test",
        }
        controller._system_info = ICSystemInfo("SYS01", params)

        # Test with missing objectList
        msg = {"command": "NotifyList"}
        controller._on_notification(msg)  # Should not raise

        # Test with invalid objectList format
        msg = {"command": "NotifyList", "objectList": "not a list"}
        controller._on_notification(msg)  # Should not raise

    def test_on_notification_updates_system_info(self, controller, model):
        """Test _on_notification updates ICSystemInfo when system object changes."""
        # Add system info with initial values
        params = {
            "PROPNAME": "Old Pool",
            "VER": "1.0.0",
            "MODE": "ENGLISH",
            "SNAME": "TestSystem",
        }
        controller._system_info = ICSystemInfo("SYS01", params)

        # Add system object to model
        model.add_object("SYS01", {"OBJTYP": "SYSTEM", "SNAME": "System", "PROPNAME": "Old Pool"})

        # Simulate notification updating system object
        msg = {
            "command": "NotifyList",
            "objectList": [{"objnam": "SYS01", "params": {"PROPNAME": "New Pool"}}],
        }
        controller._on_notification(msg)

        # System info should be updated
        assert controller._system_info.prop_name == "New Pool"

    def test_get_circuit_groups(self, controller, model):
        """Test get_circuit_groups returns parent circuits, not member rows."""
        model.add_object(
            "CG001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LITSHO", "SNAME": "Light Group 1"}
        )
        model.add_object(
            "CG002", {"OBJTYP": "CIRCUIT", "SUBTYP": "CIRCGRP", "SNAME": "Light Group 2"}
        )
        model.add_object("ROW001", {"OBJTYP": "CIRCGRP", "PARENT": "CG001", "CIRCUIT": "C001"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Light"})

        groups = controller.get_circuit_groups()

        assert len(groups) == 2
        assert all(obj.objtype == "CIRCUIT" for obj in groups)

    def test_get_circuits_in_group(self, controller, model):
        """Test get_circuits_in_group returns circuits belonging to a group."""
        # Create circuits
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Pool Light"})
        model.add_object("C002", {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Spa Light"})
        model.add_object("C003", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Deck Light"})
        # Create circuit group with space-separated circuit refs
        model.add_object(
            "CG001",
            {"OBJTYP": "CIRCGRP", "SNAME": "All Lights", "CIRCUIT": "C001 C002 C003"},
        )

        circuits = controller.get_circuits_in_group("CG001")

        assert len(circuits) == 3
        objnams = {c.objnam for c in circuits}
        assert objnams == {"C001", "C002", "C003"}

    def test_get_circuits_in_group_empty(self, controller, model):
        """Test get_circuits_in_group returns empty list for empty group."""
        model.add_object("CG001", {"OBJTYP": "CIRCGRP", "SNAME": "Empty Group"})

        circuits = controller.get_circuits_in_group("CG001")

        assert circuits == []

    def test_get_circuits_in_group_invalid_objnam(self, controller, model):
        """Test get_circuits_in_group returns empty list for invalid objnam."""
        circuits = controller.get_circuits_in_group("NONEXISTENT")
        assert circuits == []

    def test_get_circuits_in_group_wrong_type(self, controller, model):
        """Test get_circuits_in_group returns empty for non-CIRCGRP objects."""
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Light"})

        circuits = controller.get_circuits_in_group("C001")

        assert circuits == []

    def test_circuit_group_has_color_lights_true(self, controller, model):
        """Test circuit_group_has_color_lights returns True when group has color lights."""
        # Create circuits - INTELLI and MAGIC2 support color effects
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Pool Light"})
        model.add_object("C002", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Deck Light"})
        # Create circuit group
        model.add_object(
            "CG001",
            {"OBJTYP": "CIRCGRP", "SNAME": "All Lights", "CIRCUIT": "C001 C002"},
        )

        assert controller.circuit_group_has_color_lights("CG001") is True

    def test_circuit_group_has_color_lights_false(self, controller, model):
        """Test circuit_group_has_color_lights returns False when no color lights."""
        # Create circuits - LIGHT subtype does not support color effects
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Deck Light"})
        model.add_object("C002", {"OBJTYP": "CIRCUIT", "SUBTYP": "DIMMER", "SNAME": "Path Light"})
        # Create circuit group
        model.add_object(
            "CG001",
            {"OBJTYP": "CIRCGRP", "SNAME": "Non-Color Lights", "CIRCUIT": "C001 C002"},
        )

        assert controller.circuit_group_has_color_lights("CG001") is False

    def test_circuit_group_has_color_lights_empty_group(self, controller, model):
        """Test circuit_group_has_color_lights returns False for empty group."""
        model.add_object("CG001", {"OBJTYP": "CIRCGRP", "SNAME": "Empty Group"})

        assert controller.circuit_group_has_color_lights("CG001") is False

    def test_get_color_light_groups(self, controller, model):
        """Test get_color_light_groups returns only groups with color lights."""
        # Create circuits
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Pool Light"})
        model.add_object("C002", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Deck Light"})
        # Create circuit-group parents and membership rows
        model.add_object(
            "CG001",
            {"OBJTYP": "CIRCUIT", "SUBTYP": "LITSHO", "SNAME": "Color Group"},
        )
        model.add_object(
            "CG002",
            {"OBJTYP": "CIRCUIT", "SUBTYP": "LITSHO", "SNAME": "Non-Color Group"},
        )
        model.add_object("CG003", {"OBJTYP": "CIRCUIT", "SUBTYP": "LITSHO", "SNAME": "Empty Group"})
        model.add_object("ROW001", {"OBJTYP": "CIRCGRP", "PARENT": "CG001", "CIRCUIT": "C001"})
        model.add_object("ROW002", {"OBJTYP": "CIRCGRP", "PARENT": "CG002", "CIRCUIT": "C002"})

        color_groups = controller.get_color_light_groups()

        assert len(color_groups) == 1
        assert color_groups[0].objnam == "CG001"

    def test_get_all_entities_includes_circuit_groups(self, controller, model):
        """Test get_all_entities includes circuit_groups and color_light_groups."""
        # Create color light
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Pool Light"})
        # Create circuit-group parent with a color-light membership row
        model.add_object(
            "CG001",
            {"OBJTYP": "CIRCUIT", "SUBTYP": "LITSHO", "SNAME": "Color Group"},
        )
        model.add_object("ROW001", {"OBJTYP": "CIRCGRP", "PARENT": "CG001", "CIRCUIT": "C001"})

        entities = controller.get_all_entities()

        assert "circuit_groups" in entities
        assert "color_light_groups" in entities
        assert len(entities["circuit_groups"]) == 1
        assert len(entities["color_light_groups"]) == 1

    @pytest.mark.asyncio
    async def test_set_light_effect_uses_act_attr(self, controller):
        """Regression test: set_light_effect must use ACT attribute, not USE.

        IntelliCenter returns 404 when USE is sent via SETPARAMLIST. The ACT
        attribute is the action trigger; USE reflects current state read-only.
        Regression introduced in v0.1.8 (pump speed commit) and fixed in v0.1.15.
        """
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        await controller.set_light_effect("C001", "PARTY")

        call_args = controller._connection.send_request.call_args
        assert call_args[0][0] == "SETPARAMLIST"
        params = call_args[1]["objectList"][0]["params"]
        assert "ACT" in params, "set_light_effect must send ACT attribute (not USE)"
        assert params["ACT"] == "PARTY"
        assert "USE" not in params, "set_light_effect must NOT send USE attribute"

    @pytest.mark.asyncio
    async def test_set_light_effect_invalid_raises(self, controller):
        """Test set_light_effect raises ValueError for unknown effect codes."""
        with pytest.raises(ValueError, match="Invalid effect"):
            await controller.set_light_effect("C001", "NOTANEFFECT")

    def test_get_light_effect_reads_use_attr(self, controller, model):
        """Test get_light_effect reads USE attribute (state reflection)."""
        model.add_object(
            "C001",
            {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Light", "USE": "CARIB"},
        )
        assert controller.get_light_effect("C001") == "CARIB"

    def test_get_light_effect_none_for_missing(self, controller, model):
        """Test get_light_effect returns None when object doesn't exist."""
        assert controller.get_light_effect("NONEXISTENT") is None

    def test_sam_light_show_effect_is_known(self, controller):
        """Regression test for intellicenter#47: the SAm light show must map.

        IntelliCenter reports the SAm light show as USE=SAMMOD. It was missing
        from LIGHT_EFFECTS, so consumers resolved the effect name to None.
        """
        effects = controller.get_available_light_effects()
        assert "SAMMOD" in effects
        assert effects["SAMMOD"] == "SAm"

    def test_get_light_effect_name_resolves_sam(self, controller, model):
        """A light reporting USE=SAMMOD resolves to the SAm effect name."""
        model.add_object(
            "C001",
            {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Light", "USE": "SAMMOD"},
        )
        assert controller.get_light_effect_name("C001") == "SAm"


class TestMutationLifecycle:
    """Test exclusive controller mutation lifecycle behavior."""

    @pytest.fixture
    def controller(self):
        """Create a connected controller with a deterministic transport fake."""
        ctrl = ICModelController("192.168.1.100", PoolModel(), 6681)
        ctrl._connection = MagicMock()
        ctrl._connection.connected = True
        ctrl._connection.send_request = AsyncMock(return_value={"response": "200"})
        return ctrl

    @pytest.mark.asyncio
    async def test_sync_pending_rejects_all_writer_spellings_but_allows_reads(self, controller):
        """Later object writers fail fast while read-only requests stay live."""
        async with controller._light_group_mutation_lifecycle():
            for command in (
                "SETPARAMLIST",
                "SetParamList",
                "setparamlist",
                "sEtPaRaMlIsT",
            ):
                with pytest.raises(ICError, match="Color Sync mutation lifecycle"):
                    await controller.send_cmd(command, {"objectList": []})

            with pytest.raises(ICError, match="Color Sync mutation lifecycle"):
                await controller.request_changes("C001", {"STATUS": "ON"})

            with pytest.raises(ICError, match="Color Sync mutation lifecycle"):
                async with controller._light_group_mutation_lifecycle():
                    pytest.fail("a second Sync must never acquire the lifecycle")

            assert await controller.send_cmd("GetParamList") == {"response": "200"}

        controller._connection.send_request.assert_awaited_once_with("GetParamList")

    @pytest.mark.asyncio
    async def test_sync_marks_pending_before_draining_an_already_started_writer(self, controller):
        """A writer owning the lifecycle drains, while a later writer is rejected."""
        writer_started = asyncio.Event()
        release_writer = asyncio.Event()
        sync_owned = asyncio.Event()

        async def slow_send(*args, **kwargs):
            writer_started.set()
            await release_writer.wait()
            return {"response": "200"}

        controller._connection.send_request = slow_send
        first_writer = asyncio.create_task(controller.send_cmd("SetParamList", {"objectList": []}))
        await writer_started.wait()

        async def own_sync_lifecycle():
            async with controller._light_group_mutation_lifecycle():
                sync_owned.set()

        sync_task = asyncio.create_task(own_sync_lifecycle())
        await asyncio.sleep(0)
        assert controller._light_group_mutation_pending is True
        assert sync_owned.is_set() is False

        with pytest.raises(ICError, match="Color Sync mutation lifecycle"):
            await controller.send_cmd("SETPARAMLIST", {"objectList": []})

        release_writer.set()
        await first_writer
        await sync_task
        assert sync_owned.is_set() is True
        assert controller._light_group_mutation_pending is False

    @pytest.mark.asyncio
    async def test_sync_wait_cancellation_clears_pending(self, controller):
        """Cancellation while waiting for an older writer restores admission."""

        async def wait_for_sync_lifecycle():
            async with controller._light_group_mutation_lifecycle():
                pytest.fail("cancelled waiter must not acquire the lifecycle")

        async with controller._mutation_lifecycle():
            waiter = asyncio.create_task(wait_for_sync_lifecycle())
            await asyncio.sleep(0)
            assert controller._light_group_mutation_pending is True
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert controller._light_group_mutation_pending is False

    @pytest.mark.asyncio
    async def test_sync_owner_cancellation_releases_every_lifecycle_field(self, controller):
        """Cancellation after ownership invalidates the lease before unlock."""
        owned = asyncio.Event()

        async def hold_sync_lifecycle():
            async with controller._light_group_mutation_lifecycle():
                owned.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(hold_sync_lifecycle())
        await owned.wait()
        assert controller._mutation_lock.locked() is True
        assert controller._mutation_owner is task
        assert controller._light_group_mutation_lease is not None

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert controller._mutation_lock.locked() is False
        assert controller._mutation_owner is None
        assert controller._light_group_mutation_lease is None
        assert controller._light_group_mutation_pending is False

    @pytest.mark.asyncio
    async def test_exact_lease_authorizes_one_delegated_request(self, controller):
        """Only the current opaque lease can use the captured-connection primitive."""
        connection = controller._connection
        before = MagicMock()
        after = MagicMock()

        async with controller._light_group_mutation_lifecycle() as lease:
            result = await asyncio.create_task(
                controller._send_cmd_on_connection_unlocked(
                    connection,
                    "SetParamList",
                    {"objectList": []},
                    _mutation_lease=lease,
                    request_timeout=60.0,
                    _before_write_callback=before,
                    _after_write_callback=after,
                )
            )
            assert result == {"response": "200"}

            with pytest.raises(ICError, match="lease"):
                await controller._send_cmd_on_connection_unlocked(
                    connection,
                    "SetParamList",
                    _mutation_lease=object(),
                )

        with pytest.raises(ICError, match="lease"):
            await controller._send_cmd_on_connection_unlocked(
                connection,
                "SetParamList",
                _mutation_lease=lease,
            )

        connection.send_request.assert_awaited_once_with(
            "SetParamList",
            request_timeout=60.0,
            _before_write_callback=before,
            _after_write_callback=after,
            objectList=[],
        )

    @pytest.mark.asyncio
    async def test_unlocked_request_rejects_replaced_connection(self, controller):
        """The private primitive never falls through to a replacement connection."""
        old_connection = controller._connection

        async with controller._light_group_mutation_lifecycle() as lease:
            replacement = MagicMock()
            replacement.connected = True
            replacement.send_request = AsyncMock(return_value={"response": "200"})
            controller._connection = replacement

            with pytest.raises(ICConnectionError, match="changed"):
                await controller._send_cmd_on_connection_unlocked(
                    old_connection,
                    "GetParamList",
                    _mutation_lease=lease,
                )

        old_connection.send_request.assert_not_awaited()
        replacement.send_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_queue_helpers_fail_before_touching_coalescing_state(self, controller):
        """Busy checks run synchronously before either coalescing helper queues."""
        await controller._coalesce_lock.acquire()
        controller._light_group_mutation_pending = True
        try:
            with pytest.raises(ICError, match="Color Sync mutation lifecycle"):
                await controller._queue_property_change("C001", {"STATUS": "ON"})
            with pytest.raises(ICError, match="Color Sync mutation lifecycle"):
                await controller._queue_batch_changes({"C002": {"STATUS": "ON"}})
            assert controller._pending_changes == {}
            assert controller._pending_requests == []
        finally:
            controller._light_group_mutation_pending = False
            controller._coalesce_lock.release()

    @pytest.mark.asyncio
    async def test_busy_flush_completes_every_detached_waiter(self, controller):
        """A busy ICError is fanned out without orphaning coalesced futures."""
        await controller._coalesce_lock.acquire()
        first = asyncio.create_task(controller.set_circuit_state("C001", True))
        second = asyncio.create_task(controller.set_circuit_state("C002", True))
        await asyncio.sleep(0)
        controller._light_group_mutation_pending = True
        controller._coalesce_lock.release()

        results = await asyncio.gather(first, second, return_exceptions=True)
        assert all(isinstance(result, ICError) for result in results)
        assert results[0] is results[1]
        assert controller._pending_changes == {}
        assert controller._pending_requests == []
        controller._connection.send_request.assert_not_awaited()
        controller._light_group_mutation_pending = False

    @pytest.mark.asyncio
    async def test_pre_detach_cancellation_rebuilds_latest_wins_batch(self, controller):
        """Removing a queued override restores the surviving admitted value."""
        await controller._coalesce_lock.acquire()
        first = asyncio.create_task(controller.set_circuit_state("C001", True))
        await asyncio.sleep(0)
        cancelled = asyncio.create_task(controller.set_circuit_state("C001", False))
        await asyncio.sleep(0)

        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert controller._pending_changes == {"C001": {"STATUS": "ON"}}
        assert len(controller._pending_requests) == 1

        controller._coalesce_lock.release()
        await first
        sent = controller._connection.send_request.await_args.kwargs["objectList"]
        assert sent == [{"objnam": "C001", "params": {"STATUS": "ON"}}]

    @pytest.mark.asyncio
    async def test_pre_detach_cancellation_removes_distinct_object(self, controller):
        """A cancelled distinct-object request cannot leak into a later batch."""
        await controller._coalesce_lock.acquire()
        survivor = asyncio.create_task(controller.set_circuit_state("C001", True))
        await asyncio.sleep(0)
        cancelled = asyncio.create_task(controller.set_circuit_state("C002", True))
        await asyncio.sleep(0)

        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert controller._pending_changes == {"C001": {"STATUS": "ON"}}

        controller._coalesce_lock.release()
        await survivor
        sent = controller._connection.send_request.await_args.kwargs["objectList"]
        assert sent == [{"objnam": "C001", "params": {"STATUS": "ON"}}]

    @pytest.mark.asyncio
    async def test_detached_flush_owner_cancellation_marks_peers_uncertain(self, controller):
        """A possibly dispatched batch is never requeued after owner cancellation."""
        send_started = asyncio.Event()

        async def suspended_send(*args, **kwargs):
            send_started.set()
            await asyncio.Event().wait()

        controller._connection.send_request = suspended_send
        await controller._coalesce_lock.acquire()
        owner = asyncio.create_task(controller.set_circuit_state("C001", True))
        peer = asyncio.create_task(controller.set_circuit_state("C002", True))
        await asyncio.sleep(0)
        controller._coalesce_lock.release()
        await send_started.wait()

        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        with pytest.raises(ICError, match="delivery is unknown"):
            await peer

        assert controller._pending_changes == {}
        assert controller._pending_requests == []

    @pytest.mark.asyncio
    async def test_completed_peer_never_flushes_a_later_callers_batch(self, controller):
        """A request detached by an earlier flush cannot own unrelated work."""
        first_send_started = asyncio.Event()
        release_first_send = asyncio.Event()
        second_send_started = asyncio.Event()
        release_second_send = asyncio.Event()
        call_count = 0

        async def scripted_send(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_send_started.set()
                await release_first_send.wait()
                raise ICConnectionError("first batch failed")
            second_send_started.set()
            await release_second_send.wait()
            return {"response": "200"}

        controller._connection.send_request = scripted_send
        await controller._coalesce_lock.acquire()
        first_owner = asyncio.create_task(controller.set_circuit_state("C001", True))
        completed_peer = asyncio.create_task(controller.set_circuit_state("C002", True))
        await asyncio.sleep(0)
        controller._coalesce_lock.release()
        await first_send_started.wait()

        later_caller = asyncio.create_task(controller.set_circuit_state("C003", True))
        await asyncio.sleep(0)
        release_first_send.set()

        with pytest.raises(ICConnectionError, match="first batch failed"):
            await first_owner
        await second_send_started.wait()
        assert completed_peer.done() is True
        with pytest.raises(ICConnectionError, match="first batch failed"):
            await completed_peer

        release_second_send.set()
        assert await later_caller == {"response": "200"}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_cancelled_detached_caller_consumes_completed_exception(self, controller):
        """Caller cancellation retrieves an already-completed detached failure."""
        await controller._coalesce_lock.acquire()
        caller = asyncio.create_task(controller.set_circuit_state("C001", True))
        await asyncio.sleep(0)
        request = controller._pending_requests[0]

        # Model the atomic state immediately after another flush detached this
        # caller, then completed its future before the lock waiter resumed.
        controller._pending_requests = []
        controller._pending_changes = {}
        request.future.set_exception(ICError("detached batch failed"))

        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert request.future.done() is True
        assert request.future._log_traceback is False
        controller._coalesce_lock.release()


class TestRequestCoalescing:
    """Test request coalescing behavior in ICModelController."""

    @pytest.fixture
    def model(self):
        """Create a PoolModel instance."""
        return PoolModel()

    @pytest.fixture
    def controller(self, model):
        """Create an ICModelController instance with mock connection."""
        ctrl = ICModelController("192.168.1.100", model, 6681)
        ctrl._connection = MagicMock()
        ctrl._connection.connected = True
        ctrl._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )
        return ctrl

    @pytest.mark.asyncio
    async def test_single_request_sends_immediately(self, controller):
        """Test that a single request sends immediately without waiting."""
        await controller.set_circuit_state("C001", True)

        # Should have sent exactly one request
        controller._connection.send_request.assert_called_once()
        call_args = controller._connection.send_request.call_args
        assert call_args[0][0] == "SETPARAMLIST"
        assert len(call_args[1]["objectList"]) == 1
        assert call_args[1]["objectList"][0]["objnam"] == "C001"

    @pytest.mark.asyncio
    async def test_sequential_requests_send_separately(self, controller):
        """Test that sequential requests with awaits send separately."""
        await controller.set_circuit_state("C001", True)
        await controller.set_circuit_state("C002", True)

        # Should have sent two separate requests
        assert controller._connection.send_request.call_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_requests_batched_together(self, controller):
        """Test that concurrent requests are batched into one SETPARAMLIST."""
        # Create a slow mock that allows batching
        response_event = asyncio.Event()
        call_count = [0]
        captured_kwargs = []

        async def slow_send(*args, **kwargs):
            call_count[0] += 1
            captured_kwargs.append(kwargs)
            # First call waits, allowing other requests to queue
            if call_count[0] == 1:
                await response_event.wait()
            return {"response": "200", "objectList": []}

        controller._connection.send_request = slow_send

        # Launch multiple requests concurrently
        task1 = asyncio.create_task(controller.set_circuit_state("C001", True))
        await asyncio.sleep(0.01)  # Let first request acquire lock
        task2 = asyncio.create_task(controller.set_circuit_state("C002", True))
        task3 = asyncio.create_task(controller.set_circuit_state("C003", True))

        await asyncio.sleep(0.01)  # Let tasks queue up
        response_event.set()  # Release first request

        # Wait for all tasks
        await asyncio.gather(task1, task2, task3)

        # First batch has C001, second batch has C002+C003 (or all batched together)
        # The exact batching depends on timing, but total objects should be 3
        total_objects = sum(len(kw["objectList"]) for kw in captured_kwargs)
        assert total_objects == 3

    @pytest.mark.asyncio
    async def test_latest_value_wins_same_object_attr(self, controller):
        """Test that latest value wins for same (objnam, attribute)."""
        response_event = asyncio.Event()
        captured_kwargs = []

        async def slow_send(*args, **kwargs):
            captured_kwargs.append(kwargs)
            if len(captured_kwargs) == 1:
                await response_event.wait()
            return {"response": "200", "objectList": []}

        controller._connection.send_request = slow_send

        # First request acquires lock
        task1 = asyncio.create_task(controller.set_circuit_state("C001", True))
        await asyncio.sleep(0.01)

        # These queue up with conflicting values for same circuit
        task2 = asyncio.create_task(controller.set_circuit_state("C001", False))
        task3 = asyncio.create_task(controller.set_circuit_state("C001", True))
        task4 = asyncio.create_task(controller.set_circuit_state("C001", False))  # Latest

        await asyncio.sleep(0.01)
        response_event.set()

        await asyncio.gather(task1, task2, task3, task4)

        # First request has ON, second batch should have OFF (latest wins)
        assert len(captured_kwargs) == 2
        first_batch = captured_kwargs[0]["objectList"]
        second_batch = captured_kwargs[1]["objectList"]

        assert len(first_batch) == 1
        assert first_batch[0]["params"]["STATUS"] == "ON"

        assert len(second_batch) == 1
        assert second_batch[0]["objnam"] == "C001"
        assert second_batch[0]["params"]["STATUS"] == "OFF"

    @pytest.mark.asyncio
    async def test_different_attrs_same_object_merged(self, controller):
        """Test that different attributes on same object are merged."""
        response_event = asyncio.Event()
        captured_kwargs = []

        async def slow_send(*args, **kwargs):
            captured_kwargs.append(kwargs)
            if len(captured_kwargs) == 1:
                await response_event.wait()
            return {"response": "200", "objectList": []}

        controller._connection.send_request = slow_send

        # First request acquires lock
        task1 = asyncio.create_task(controller.set_setpoint("B001", 80))
        await asyncio.sleep(0.01)

        # Queue heat mode change for same body - should merge with same objnam
        from pyintellicenter import HeaterType

        task2 = asyncio.create_task(controller.set_heat_mode("B001", HeaterType.HEATER))

        await asyncio.sleep(0.01)
        response_event.set()

        await asyncio.gather(task1, task2)

        # Second batch should have both LOTMP and MODE in one object entry
        assert len(captured_kwargs) == 2
        second_batch = captured_kwargs[1]["objectList"]
        assert len(second_batch) == 1
        assert second_batch[0]["objnam"] == "B001"
        assert "MODE" in second_batch[0]["params"]

    @pytest.mark.asyncio
    async def test_error_propagates_to_all_waiters(self, controller):
        """Test that errors propagate to all waiting requests."""
        response_event = asyncio.Event()
        call_count = [0]

        async def failing_send(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                await response_event.wait()
            raise ICConnectionError("Connection lost")

        controller._connection.send_request = failing_send

        # First request acquires lock
        task1 = asyncio.create_task(controller.set_circuit_state("C001", True))
        await asyncio.sleep(0.01)

        # Queue more requests
        task2 = asyncio.create_task(controller.set_circuit_state("C002", True))
        task3 = asyncio.create_task(controller.set_circuit_state("C003", True))

        await asyncio.sleep(0.01)
        response_event.set()

        # All tasks should get the same error
        with pytest.raises(ICConnectionError):
            await task1

        with pytest.raises(ICConnectionError):
            await task2

        with pytest.raises(ICConnectionError):
            await task3

    @pytest.mark.asyncio
    async def test_direct_request_changes_bypasses_coalescing(self, controller):
        """Test that request_changes() bypasses coalescing mechanism."""
        # The direct API should send immediately without coalescing
        await controller.request_changes("C001", {"STATUS": "ON"})
        await controller.request_changes("C002", {"STATUS": "ON"})

        # Should have sent two separate requests
        assert controller._connection.send_request.call_count == 2

    @pytest.mark.asyncio
    async def test_multiple_objects_batched_correctly(self, controller):
        """Test that multiple different objects are batched into one request."""
        response_event = asyncio.Event()
        captured_kwargs = []

        async def slow_send(*args, **kwargs):
            captured_kwargs.append(kwargs)
            if len(captured_kwargs) == 1:
                await response_event.wait()
            return {"response": "200", "objectList": []}

        controller._connection.send_request = slow_send

        # First request acquires lock
        task1 = asyncio.create_task(controller.set_circuit_state("C001", True))
        await asyncio.sleep(0.01)

        # Queue requests for different objects
        task2 = asyncio.create_task(controller.set_circuit_state("C002", True))
        task3 = asyncio.create_task(controller.set_circuit_state("C003", True))
        task4 = asyncio.create_task(controller.set_setpoint("B001", 85))

        await asyncio.sleep(0.01)
        response_event.set()

        await asyncio.gather(task1, task2, task3, task4)

        # Second batch should have all 3 different objects
        assert len(captured_kwargs) == 2
        second_batch = captured_kwargs[1]["objectList"]
        assert len(second_batch) == 3
        objnams = {obj["objnam"] for obj in second_batch}
        assert objnams == {"C002", "C003", "B001"}

    @pytest.mark.asyncio
    async def test_set_multiple_circuits_uses_coalescing(self, controller):
        """Test that set_multiple_circuit_states uses coalescing correctly."""
        await controller.set_multiple_circuit_states(["C001", "C002", "C003"], True)

        # Should send all in one request
        controller._connection.send_request.assert_called_once()
        call_args = controller._connection.send_request.call_args
        object_list = call_args[1]["objectList"]
        assert len(object_list) == 3

    @pytest.mark.asyncio
    async def test_coalescing_preserves_response(self, controller):
        """Test that coalesced requests all receive the correct response."""
        expected_response = {
            "response": "200",
            "objectList": [{"objnam": "C001", "params": {"STATUS": "ON"}}],
        }
        controller._connection.send_request = AsyncMock(return_value=expected_response)

        result = await controller.set_circuit_state("C001", True)

        assert result == expected_response

    # =========================================================================
    # Pump Circuit Helper Tests
    # =========================================================================

    def test_get_pump_circuits(self, controller):
        """Test get_pump_circuits returns all PMPCIRC objects."""
        # Add pump and pump circuit objects
        controller._model.add_object(
            "PUMP1",
            {
                "OBJTYP": "PUMP",
                "SUBTYP": "VSF",
                "SNAME": "Pool Pump",
                "MIN": "450",
                "MAX": "3450",
                "MINF": "15",
                "MAXF": "140",
            },
        )
        controller._model.add_object(
            "PMPCIRC01",
            {
                "OBJTYP": "PMPCIRC",
                "SNAME": "Pool Circuit",
                "PARENT": "PUMP1",
                "SELECT": "RPM",
                "SPEED": "2400",
            },
        )

        circuits = controller.get_pump_circuits()
        assert len(circuits) == 1
        assert circuits[0].objnam == "PMPCIRC01"

    def test_get_pump_circuit_speed_rpm_mode(self, controller):
        """Test get_pump_circuit_speed returns clamped value in RPM mode."""
        # Add pump and pump circuit
        controller._model.add_object(
            "PUMP1",
            {
                "OBJTYP": "PUMP",
                "SUBTYP": "VSF",
                "MIN": "450",
                "MAX": "3450",
                "MINF": "15",
                "MAXF": "140",
            },
        )
        controller._model.add_object(
            "PMPCIRC01",
            {
                "OBJTYP": "PMPCIRC",
                "PARENT": "PUMP1",
                "SELECT": "RPM",
                "SPEED": "2400",
            },
        )

        speed = controller.get_pump_circuit_speed("PMPCIRC01")
        assert speed == 2400

    def test_get_pump_circuit_speed_gpm_mode(self, controller):
        """Test get_pump_circuit_speed returns clamped value in GPM mode."""
        controller._model.add_object(
            "PUMP1",
            {
                "OBJTYP": "PUMP",
                "SUBTYP": "VSF",
                "MIN": "450",
                "MAX": "3450",
                "MINF": "15",
                "MAXF": "140",
            },
        )
        controller._model.add_object(
            "PMPCIRC01",
            {
                "OBJTYP": "PMPCIRC",
                "PARENT": "PUMP1",
                "SELECT": "GPM",
                "SPEED": "80",
            },
        )

        speed = controller.get_pump_circuit_speed("PMPCIRC01")
        assert speed == 80

    def test_get_pump_circuit_speed_returns_none_for_stale_gpm_value(self, controller):
        """Test speed returns None when stale RPM value is outside GPM range.

        When switching from RPM (e.g., 450) to GPM mode, the stale SPEED value
        (450) is outside the valid GPM range (15-140), so return None to indicate
        the value is unavailable until IntelliCenter sends the real value.
        """
        controller._model.add_object(
            "PUMP1",
            {
                "OBJTYP": "PUMP",
                "SUBTYP": "VSF",
                "MIN": "450",
                "MAX": "3450",
                "MINF": "15",
                "MAXF": "140",
            },
        )
        controller._model.add_object(
            "PMPCIRC01",
            {
                "OBJTYP": "PMPCIRC",
                "PARENT": "PUMP1",
                "SELECT": "GPM",  # Mode switched to GPM
                "SPEED": "450",  # But SPEED still has old RPM value (stale)
            },
        )

        # Should return None since 450 is outside GPM range (15-140)
        speed = controller.get_pump_circuit_speed("PMPCIRC01")
        assert speed is None

    def test_get_pump_circuit_speed_returns_none_for_stale_rpm_value(self, controller):
        """Test speed returns None when stale GPM value is outside RPM range."""
        controller._model.add_object(
            "PUMP1",
            {
                "OBJTYP": "PUMP",
                "SUBTYP": "VSF",
                "MIN": "450",
                "MAX": "3450",
                "MINF": "15",
                "MAXF": "140",
            },
        )
        controller._model.add_object(
            "PMPCIRC01",
            {
                "OBJTYP": "PMPCIRC",
                "PARENT": "PUMP1",
                "SELECT": "RPM",  # Mode switched to RPM
                "SPEED": "80",  # But SPEED still has old GPM value (stale)
            },
        )

        # Should return None since 80 is outside RPM range (450-3450)
        speed = controller.get_pump_circuit_speed("PMPCIRC01")
        assert speed is None

    def test_get_pump_circuit_speed_returns_none_for_missing_object(self, controller):
        """Test get_pump_circuit_speed returns None for non-existent object."""
        speed = controller.get_pump_circuit_speed("NONEXISTENT")
        assert speed is None

    def test_get_pump_circuit_speed_returns_none_for_non_pmpcirc(self, controller):
        """Test get_pump_circuit_speed returns None for non-PMPCIRC object."""
        controller._model.add_object(
            "PUMP1",
            {
                "OBJTYP": "PUMP",
                "SUBTYP": "VSF",
            },
        )

        speed = controller.get_pump_circuit_speed("PUMP1")
        assert speed is None

    def test_get_pump_circuit_mode(self, controller):
        """Test get_pump_circuit_mode returns current mode."""
        controller._model.add_object(
            "PMPCIRC01",
            {
                "OBJTYP": "PMPCIRC",
                "SELECT": "GPM",
            },
        )

        mode = controller.get_pump_circuit_mode("PMPCIRC01")
        assert mode == "GPM"

    def test_get_pump_circuit_limits(self, controller):
        """Test get_pump_circuit_limits returns limits from parent pump."""
        controller._model.add_object(
            "PUMP1",
            {
                "OBJTYP": "PUMP",
                "SUBTYP": "VSF",
                "MIN": "450",
                "MAX": "3450",
                "MINF": "15",
                "MAXF": "140",
            },
        )
        controller._model.add_object(
            "PMPCIRC01",
            {
                "OBJTYP": "PMPCIRC",
                "PARENT": "PUMP1",
            },
        )

        limits = controller.get_pump_circuit_limits("PMPCIRC01")
        assert limits["rpm"]["min"] == 450
        assert limits["rpm"]["max"] == 3450
        assert limits["gpm"]["min"] == 15
        assert limits["gpm"]["max"] == 140

    @pytest.mark.asyncio
    async def test_refresh_pump_circuit_speed(self, controller):
        """Test refresh_pump_circuit_speed fetches fresh value from IntelliCenter."""
        # Add PMPCIRC to the model first
        controller._model.add_object(
            "PMPCIRC01",
            {
                "OBJTYP": "PMPCIRC",
                "PARENT": "PUMP1",
                "SELECT": "RPM",
                "SPEED": "1000",  # Old value
            },
        )

        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={
                "response": "200",
                "objectList": [{"objnam": "PMPCIRC01", "params": {"SPEED": "1500"}}],
            }
        )

        speed = await controller.refresh_pump_circuit_speed("PMPCIRC01")

        assert speed == 1500
        controller._connection.send_request.assert_called_once()
        # Verify the model was updated
        assert controller._model["PMPCIRC01"]["SPEED"] == "1500"

    @pytest.mark.asyncio
    async def test_refresh_pump_circuit_speed_returns_none_on_error(self, controller):
        """Test refresh_pump_circuit_speed returns None when request fails."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(return_value={})

        speed = await controller.refresh_pump_circuit_speed("PMPCIRC01")

        assert speed is None


class TestICConnectionHandler:
    """Test ICConnectionHandler class."""

    @pytest.fixture
    def mock_controller(self):
        """Create mock controller."""
        controller = MagicMock()
        controller.start = AsyncMock()
        controller.stop = AsyncMock()
        controller.host = "192.168.1.100"
        controller._metrics = ICConnectionMetrics()
        controller.set_disconnected_callback = MagicMock()
        return controller

    @pytest.fixture
    def handler(self, mock_controller):
        """Create ICConnectionHandler instance."""
        return ICConnectionHandler(mock_controller, time_between_reconnects=1)

    def test_init(self, handler, mock_controller):
        """Test ICConnectionHandler initialization."""
        assert handler.controller is mock_controller
        assert handler._time_between_reconnects == 1
        assert handler._first_time is True
        assert handler._stopped is False

    def test_repr(self, handler):
        """Test repr representation."""
        repr_str = repr(handler)
        assert "ICConnectionHandler" in repr_str

    @pytest.mark.asyncio
    async def test_start_connects(self, handler, mock_controller):
        """Test start connects controller."""
        started_called = False

        def on_started(controller):
            nonlocal started_called
            started_called = True

        handler.on_started = on_started

        await handler.start()
        await asyncio.sleep(0.2)

        mock_controller.start.assert_called()
        assert started_called

        # Cleanup
        handler.stop()

    @pytest.mark.asyncio
    async def test_stop(self, handler, mock_controller):
        """Test stopping handler."""
        await handler.start()
        await asyncio.sleep(0.1)

        handler.stop()

        assert handler._stopped is True

    def test_stop_is_not_a_coroutine_function(self):
        """``stop()`` is synchronous, unlike ``start()``.

        The README and docs/API.md show ``handler.stop()`` without ``await``.
        Awaiting it raises ``TypeError: object NoneType can't be used in 'await'
        expression``, so lock the contract here: if ``stop()`` ever becomes a
        coroutine, this fails and the docs get updated with it.
        """
        assert inspect.iscoroutinefunction(ICConnectionHandler.start)
        assert not inspect.iscoroutinefunction(ICConnectionHandler.stop)

    @pytest.mark.asyncio
    async def test_documented_shutdown_pattern(self, handler, mock_controller):
        """The exact start/stop pattern the README shows must work."""
        await handler.start()
        await asyncio.sleep(0.1)

        assert handler.stop() is None
        assert handler._stopped is True

    @pytest.mark.asyncio
    async def test_reconnect_on_failure(self, handler, mock_controller):
        """Test reconnection on connection failure."""
        call_count = 0

        async def failing_start():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ICConnectionError("Connection failed")

        mock_controller.start = failing_start

        # First attempt will fail and raise, but reconnection continues in background
        with pytest.raises(ICConnectionError):
            await handler.start()

        await asyncio.sleep(2.5)  # Allow time for retries (timeBetweenReconnects=1)

        handler.stop()

        # Should have attempted multiple times (reconnection continues after first failure)
        assert call_count >= 2

    def test_disconnect_callback_set(self, handler, mock_controller):
        """Test that disconnect callback is set on controller."""
        mock_controller.set_disconnected_callback.assert_called_once()

    def test_on_started_callback(self, mock_controller):
        """Test on_started callback is called."""
        handler = ICConnectionHandler(mock_controller)

        started_called = []

        def on_started(ctrl):
            started_called.append(ctrl)

        handler.on_started = on_started
        handler.on_started(mock_controller)

        assert len(started_called) == 1

    def test_on_disconnected_callback(self, mock_controller):
        """Test on_disconnected callback."""
        handler = ICConnectionHandler(mock_controller)

        disconnected_called = []

        def on_disconnected(ctrl, exc):
            disconnected_called.append((ctrl, exc))

        handler.on_disconnected = on_disconnected
        handler.on_disconnected(mock_controller, Exception("Test"))

        assert len(disconnected_called) == 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_triggers_after_failures(self, mock_controller):
        """Test circuit breaker opens after repeated failures.

        Updated for issue #62: retry delays no longer degenerate into a
        zero-delay hot loop, so sleeps are fast-forwarded instead of relying
        on the (fixed) backoff staying at zero in real time.
        """
        from pyintellicenter.controller import (
            CIRCUIT_BREAKER_FAILURES,
            CIRCUIT_BREAKER_RESET_TIME,
        )

        handler = ICConnectionHandler(mock_controller, time_between_reconnects=0)
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ICConnectionError("Connection failed")

        mock_controller.start = always_fail

        real_sleep = asyncio.sleep
        sleep_calls: list[float] = []

        async def fast_sleep(delay, *args, **kwargs):
            sleep_calls.append(delay)
            await real_sleep(0)

        with patch("asyncio.sleep", new=fast_sleep):
            task = asyncio.create_task(handler._starter())
            while CIRCUIT_BREAKER_RESET_TIME not in sleep_calls and call_count < 50:
                await real_sleep(0.001)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # The breaker opened after the documented number of failures and
        # paused for the reset time.
        assert call_count >= CIRCUIT_BREAKER_FAILURES
        assert CIRCUIT_BREAKER_RESET_TIME in sleep_calls

    @pytest.mark.asyncio
    async def test_exponential_backoff(self, mock_controller):
        """Test exponential backoff increases delay."""
        handler = ICConnectionHandler(mock_controller, time_between_reconnects=1)
        call_count = 0
        call_times = []

        async def failing_start():
            nonlocal call_count
            call_count += 1
            call_times.append(asyncio.get_event_loop().time())
            if call_count < 4:
                raise ICConnectionError("Connection failed")

        mock_controller.start = failing_start

        # First attempt will fail and raise, but reconnection continues in background
        with pytest.raises(ICConnectionError):
            await handler.start()

        await asyncio.sleep(5)  # Allow time for retries with backoff

        handler.stop()

        # Verify we got multiple attempts
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_circuit_breaker_resets_on_success(self, mock_controller):
        """Test circuit breaker resets after successful connection."""
        handler = ICConnectionHandler(mock_controller, time_between_reconnects=0)
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ICConnectionError("Connection failed")
            # Success on third attempt

        mock_controller.start = fail_then_succeed

        # First attempt will fail and raise, but reconnection continues in background
        with pytest.raises(ICConnectionError):
            await handler.start()

        # With the fixed backoff (issue #62) the delays are 0s then 1s instead
        # of a zero-delay hot loop, so wait long enough for the third attempt.
        await asyncio.sleep(1.5)

        handler.stop()

        # Should have reset failure count after success
        assert handler._failure_count == 0

    def test_on_retrying_callback_called(self, mock_controller):
        """Test on_retrying callback is invoked."""
        handler = ICConnectionHandler(mock_controller)

        retrying_delays = []

        def on_retrying(delay):
            retrying_delays.append(delay)

        handler.on_retrying = on_retrying
        handler.on_retrying(30)

        assert len(retrying_delays) == 1
        assert retrying_delays[0] == 30

    @pytest.mark.asyncio
    async def test_handles_timeout_error(self, mock_controller):
        """Test handler handles TimeoutError during connection."""
        handler = ICConnectionHandler(mock_controller, time_between_reconnects=0)
        call_count = 0

        async def timeout_start():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("Connection timed out")

        mock_controller.start = timeout_start

        # First attempt will fail and raise, but reconnection continues in background
        with pytest.raises(TimeoutError):
            await handler.start()

        await asyncio.sleep(0.3)

        handler.stop()

        # Should have recovered
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_disconnect_debounce(self, mock_controller):
        """Test on_disconnected callback is debounced."""
        handler = ICConnectionHandler(
            mock_controller,
            time_between_reconnects=0,
            disconnect_debounce_time=1,  # 1 second debounce
        )

        disconnected_calls = []

        def on_disconnected(ctrl, exc):
            disconnected_calls.append((ctrl, exc))

        handler.on_disconnected = on_disconnected

        # Simulate quick disconnect/reconnect
        await handler.start()
        await asyncio.sleep(0.1)

        # Trigger disconnect
        handler._on_disconnect(mock_controller, Exception("Test"))

        # Wait less than debounce time
        await asyncio.sleep(0.2)

        # Disconnect callback should not have been called yet
        assert len(disconnected_calls) == 0

        handler.stop()

    @pytest.mark.asyncio
    async def test_disconnect_callback_after_debounce(self, mock_controller):
        """Test on_disconnected callback is called after debounce period."""
        handler = ICConnectionHandler(
            mock_controller,
            time_between_reconnects=10,  # Long delay to prevent reconnect
            disconnect_debounce_time=0,  # No debounce
        )

        disconnected_calls = []

        def on_disconnected(ctrl, exc):
            disconnected_calls.append((ctrl, exc))

        handler.on_disconnected = on_disconnected
        handler._first_time = False  # Pretend we've connected before

        # Trigger disconnect
        handler._on_disconnect(mock_controller, Exception("Test disconnect"))

        # Wait for debounce to complete
        await asyncio.sleep(0.2)

        # Disconnect callback should have been called
        assert len(disconnected_calls) == 1

        handler.stop()

    @pytest.mark.asyncio
    async def test_on_reconnected_callback(self, mock_controller):
        """Test on_reconnected callback is called after reconnection."""
        handler = ICConnectionHandler(mock_controller, time_between_reconnects=0)

        reconnected_calls = []
        started_calls = []

        def on_started(ctrl):
            started_calls.append(ctrl)

        def on_reconnected(ctrl):
            reconnected_calls.append(ctrl)

        handler.on_started = on_started
        handler.on_reconnected = on_reconnected

        # First connection
        await handler.start()
        await asyncio.sleep(0.1)

        assert len(started_calls) == 1
        assert len(reconnected_calls) == 0

        # Simulate disconnect and reconnect
        handler._is_connected = False
        handler._first_time = False

        # Start reconnection
        handler._starter_task = asyncio.create_task(handler._starter())
        await asyncio.sleep(0.2)

        # Should have called reconnected
        assert len(reconnected_calls) == 1

        handler.stop()

    @pytest.mark.asyncio
    async def test_on_updated_callback_on_model_controller(self):
        """Test on_updated callback is set on ICModelController."""
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        handler = ICConnectionHandler(controller)

        # Verify callback is connected (ICConnectionHandler sets it in __init__)
        assert controller._updated_callback is not None

        handler.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_debounce_task(self, mock_controller):
        """Test stop cancels any pending debounce task."""
        handler = ICConnectionHandler(mock_controller)

        # Create a fake debounce task
        async def fake_debounce():
            await asyncio.sleep(100)

        handler._disconnect_debounce_task = asyncio.create_task(fake_debounce())

        handler.stop()

        # Task should be cancelled
        assert handler._disconnect_debounce_task is None

    @pytest.mark.asyncio
    async def test_on_disconnect_starts_reconnection(self, mock_controller):
        """Test _on_disconnect starts reconnection task."""
        handler = ICConnectionHandler(mock_controller, time_between_reconnects=1)

        await handler.start()
        await asyncio.sleep(0.1)

        # Clear the starter task reference
        handler._starter_task = None

        # Trigger disconnect
        handler._on_disconnect(mock_controller, Exception("Test"))

        # Should have started a new reconnection task
        assert handler._starter_task is not None

        handler.stop()

    @pytest.mark.asyncio
    async def test_on_disconnect_does_nothing_when_stopped(self, mock_controller):
        """Test _on_disconnect does nothing when handler is stopped."""
        handler = ICConnectionHandler(mock_controller, time_between_reconnects=1)
        handler._stopped = True

        # Trigger disconnect
        handler._on_disconnect(mock_controller, Exception("Test"))

        # Should not have started any tasks
        assert handler._starter_task is None
        assert handler._disconnect_debounce_task is None


class TestHandlerLifecycle:
    """Regression tests for issue #61: tracked teardown, astop(), restart."""

    @pytest.fixture
    def mock_controller(self):
        """Create mock controller."""
        controller = MagicMock()
        controller.start = AsyncMock()
        controller.stop = AsyncMock()
        controller.host = "192.168.1.100"
        controller._metrics = ICConnectionMetrics()
        controller.set_disconnected_callback = MagicMock()
        return controller

    @pytest.fixture
    def handler(self, mock_controller):
        """Create a fast handler (no reconnect delay, no debounce)."""
        return ICConnectionHandler(
            mock_controller, time_between_reconnects=0, disconnect_debounce_time=0
        )

    @pytest.mark.asyncio
    async def test_astop_completes_full_teardown(self, handler, mock_controller):
        """astop() waits until controller.stop() has fully run."""
        await handler.start()

        await handler.astop()

        mock_controller.stop.assert_awaited_once()
        assert handler._stop_task is None
        assert handler._stopped is True
        assert handler.connected is False

    @pytest.mark.asyncio
    async def test_stop_creates_tracked_stop_task(self, handler, mock_controller):
        """stop() keeps a strong reference to the teardown task (no GC orphan)."""
        await handler.start()

        handler.stop()

        task = handler._stop_task
        assert isinstance(task, asyncio.Task)
        await task
        mock_controller.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_repeated_stop_reuses_inflight_stop_task(self, handler, mock_controller):
        """A second stop() while teardown runs must not spawn a second teardown."""
        release = asyncio.Event()

        async def slow_stop():
            await release.wait()

        mock_controller.stop = slow_stop

        handler.stop()
        first = handler._stop_task
        await asyncio.sleep(0)
        handler.stop()

        assert handler._stop_task is first
        release.set()
        await first

    @pytest.mark.asyncio
    async def test_stop_then_start_restart_supports_reconnect(self, handler, mock_controller):
        """The handler can be restarted after stop(), including reconnection.

        Previously _stopped was never reset by start(), so a restarted handler
        silently dropped every later disconnect (permanent dead state), and a
        stop() racing a restart could disown the fresh connection.
        """
        await handler.start()
        assert handler.connected is True

        await handler.astop()
        assert handler.connected is False
        assert mock_controller.stop.await_count == 1

        # Restart
        await handler.start()
        assert handler._stopped is False
        assert handler.connected is True
        assert mock_controller.start.await_count == 2

        # Reconnect after restart must not be dropped by a stale stopped flag.
        handler._on_disconnect(mock_controller, Exception("link dropped"))
        assert handler._starter_task is not None
        await asyncio.sleep(0.05)
        assert handler.connected is True
        assert mock_controller.start.await_count == 3

        await handler.astop()

    @pytest.mark.asyncio
    async def test_start_waits_for_inflight_teardown(self, handler, mock_controller):
        """start() after stop() serializes with the still-running teardown."""
        release = asyncio.Event()
        order: list[str] = []

        async def slow_stop():
            await release.wait()
            order.append("stopped")

        async def tracked_start():
            order.append("started")

        mock_controller.stop = slow_stop
        mock_controller.start = tracked_start

        handler.stop()
        restart = asyncio.create_task(handler.start())
        await asyncio.sleep(0.01)
        # start() must still be waiting on the teardown.
        assert not restart.done()
        assert order == []

        release.set()
        await asyncio.wait_for(restart, 1)
        assert order == ["stopped", "started"]

    @pytest.mark.asyncio
    async def test_cancelled_astop_still_completes_teardown(self, handler, mock_controller):
        """Cancelling an astop() caller must not cancel the teardown itself.

        Previously astop() awaited _stop_task directly, so cancelling the
        astop() caller cancelled the teardown mid-flight - with the connection
        already detached but the socket possibly never closed.
        """
        release = asyncio.Event()
        completed = asyncio.Event()

        async def slow_stop():
            await release.wait()
            completed.set()

        mock_controller.stop = slow_stop

        astop_task = asyncio.create_task(handler.astop())
        await asyncio.sleep(0.01)  # astop is now awaiting the teardown
        stop_task = handler._stop_task
        assert stop_task is not None

        astop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await astop_task

        # The shielded teardown task is still alive, and its reference is
        # retained for a later start()/astop() to await.
        assert not stop_task.cancelled()
        assert not stop_task.done()
        assert handler._stop_task is stop_task

        # The teardown still completes in the background.
        release.set()
        await asyncio.wait_for(stop_task, 1)
        assert completed.is_set()

    @pytest.mark.asyncio
    async def test_start_after_cancelled_astop_waits_for_real_teardown(
        self, handler, mock_controller
    ):
        """start() after a cancelled astop() awaits the ACTUAL teardown end.

        The still-running (shielded) teardown must fully release the old
        connection before start() opens a new one.
        """
        release = asyncio.Event()
        order: list[str] = []

        async def slow_stop():
            await release.wait()
            order.append("stopped")

        async def tracked_start():
            order.append("started")

        mock_controller.stop = slow_stop
        mock_controller.start = tracked_start

        astop_task = asyncio.create_task(handler.astop())
        await asyncio.sleep(0.01)
        astop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await astop_task

        restart = asyncio.create_task(handler.start())
        await asyncio.sleep(0.01)
        # start() must still be waiting on the surviving teardown.
        assert not restart.done()
        assert order == []

        release.set()
        await asyncio.wait_for(restart, 1)
        assert order == ["stopped", "started"]

    @pytest.mark.asyncio
    async def test_start_reruns_teardown_cancelled_mid_flight(self, handler, mock_controller):
        """A teardown task cancelled before finishing is re-run by start().

        Completion of the wait on the old stop task is not completion of the
        teardown: a cancelled/failed outcome must be inspected and the
        teardown re-run before a new connection is opened.
        """
        handler.stop()
        stop_task = handler._stop_task
        assert stop_task is not None
        # Cancel the teardown before it ever runs (e.g. loop shutdown race).
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        assert stop_task.cancelled()
        mock_controller.stop.assert_not_awaited()

        await handler.start()

        # start() re-ran the teardown to completion before connecting.
        mock_controller.stop.assert_awaited_once()
        mock_controller.start.assert_awaited_once()
        assert handler._stop_task is None
        assert handler.connected is True

        await handler.astop()

    @pytest.mark.asyncio
    async def test_connected_property_lifecycle(self, handler, mock_controller):
        """connected reflects the debounced handler-level availability."""
        assert handler.connected is False

        await handler.start()
        assert handler.connected is True

        handler._on_disconnect(mock_controller, Exception("dropped"))
        assert handler.connected is False

        await asyncio.sleep(0.05)  # zero-delay reconnect succeeds
        assert handler.connected is True

        await handler.astop()
        assert handler.connected is False

    @pytest.mark.asyncio
    async def test_model_controller_stop_cancels_monitor_tasks(self):
        """ICModelController.stop() cancels pending monitor tasks."""
        controller = ICModelController("192.168.1.100", PoolModel(), 6681)
        started = asyncio.Event()

        async def hang():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(hang())
        controller._monitor_tasks.add(task)
        task.add_done_callback(controller._on_monitor_task_done)
        await started.wait()

        await controller.stop()

        assert task.cancelled()
        assert controller._monitor_tasks == set()


class TestHandlerCallbackResilience:
    """Regression tests for issue #62: a raising user callback never kills
    the reconnect machinery or turns a successful startup into a failure."""

    @pytest.fixture
    def mock_controller(self):
        """Create mock controller."""
        controller = MagicMock()
        controller.start = AsyncMock()
        controller.stop = AsyncMock()
        controller.host = "192.168.1.100"
        controller._metrics = ICConnectionMetrics()
        controller.set_disconnected_callback = MagicMock()
        return controller

    @pytest.fixture
    def handler(self, mock_controller):
        """Create a fast handler (no reconnect delay, no debounce)."""
        return ICConnectionHandler(
            mock_controller, time_between_reconnects=0, disconnect_debounce_time=0
        )

    @pytest.mark.asyncio
    async def test_on_started_raising_does_not_fail_start(self, handler):
        """A raising on_started must not make a successful start() raise."""

        def bad_on_started(ctrl):
            raise KeyError("entity not ready")

        handler.on_started = bad_on_started

        await handler.start()  # must not raise
        assert handler.connected is True

        await handler.astop()

    @pytest.mark.asyncio
    async def test_on_retrying_raising_does_not_kill_reconnection(self, handler, mock_controller):
        """A raising on_retrying must not end the retry loop."""
        calls = 0

        async def fail_twice():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ICConnectionError("still down")

        mock_controller.start = fail_twice

        def bad_on_retrying(delay):
            raise RuntimeError("consumer bug")

        handler.on_retrying = bad_on_retrying

        with pytest.raises(ICConnectionError):
            await handler.start()

        # Backoff after the first failure is 0s then 1s.
        await asyncio.sleep(1.5)
        assert calls >= 3
        assert handler.connected is True

        await handler.astop()

    @pytest.mark.asyncio
    async def test_on_reconnected_raising_still_marks_connected(self, handler):
        """A raising on_reconnected must not lose the reconnected state."""
        handler._first_time = False
        handler._is_connected = False

        def bad_on_reconnected(ctrl):
            raise RuntimeError("consumer bug")

        handler.on_reconnected = bad_on_reconnected

        task = asyncio.create_task(handler._starter())
        await asyncio.wait_for(task, 1)

        assert handler.connected is True
        await handler.astop()

    @pytest.mark.asyncio
    async def test_on_disconnected_raising_is_contained(self, handler, mock_controller):
        """A raising on_disconnected must not kill the debounce task."""
        handler._first_time = False
        # Prevent an instant zero-delay reconnect from cancelling the debounce.
        mock_controller.start = AsyncMock(side_effect=ICConnectionError("down"))

        def bad_on_disconnected(ctrl, exc):
            raise RuntimeError("consumer bug")

        handler.on_disconnected = bad_on_disconnected

        handler._on_disconnect(mock_controller, Exception("dropped"))
        debounce = handler._disconnect_debounce_task
        assert debounce is not None
        await asyncio.sleep(0.05)

        assert debounce.done()
        assert not debounce.cancelled() and debounce.exception() is None
        await handler.astop()

    @pytest.mark.asyncio
    async def test_on_updated_raising_is_contained(self):
        """A raising on_updated must not propagate out of update dispatch."""
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        handler = ICConnectionHandler(controller, time_between_reconnects=0)

        def bad_on_updated(ctrl, updates):
            raise KeyError("entity")

        handler.on_updated = bad_on_updated

        model.add_object(
            "C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light", "STATUS": "OFF"}
        )
        # Must not raise despite the consumer callback raising.
        updates = controller._apply_updates([{"objnam": "C001", "params": {"STATUS": "ON"}}])
        assert updates["C001"]["STATUS"] == "ON"
        assert model["C001"]["STATUS"] == "ON"

        await handler.astop()

    @pytest.mark.asyncio
    async def test_updated_callback_raise_does_not_abort_new_object_monitoring(self):
        """New-object monitoring is scheduled before the update callback runs."""
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        controller.send_cmd = AsyncMock(return_value={"response": "200", "objectList": []})

        def bad_callback(ctrl, updates):
            raise KeyError("entity")

        controller.set_updated_callback(bad_callback)

        msg = {
            "command": "NotifyList",
            "objectList": [
                {
                    "objnam": "CHM02",
                    "params": {"OBJTYP": "CHEM", "SUBTYP": "ICHEM", "SNAME": "IntelliChem 2"},
                }
            ],
        }
        controller._on_notification(msg)

        # Monitoring for the new object was scheduled despite the raise.
        assert controller._monitor_tasks
        await asyncio.gather(*controller._monitor_tasks)
        request_calls = [
            call
            for call in controller.send_cmd.await_args_list
            if call.args[0] == "RequestParamList"
        ]
        assert request_calls


class TestHandlerStartContract:
    """Regression tests for issue #62: start() truthfulness and resilience."""

    @pytest.fixture
    def mock_controller(self):
        """Create mock controller."""
        controller = MagicMock()
        controller.start = AsyncMock()
        controller.stop = AsyncMock()
        controller.host = "192.168.1.100"
        controller._metrics = ICConnectionMetrics()
        controller.set_disconnected_callback = MagicMock()
        return controller

    @pytest.fixture
    def handler(self, mock_controller):
        """Create a fast handler (no reconnect delay, no debounce)."""
        return ICConnectionHandler(
            mock_controller, time_between_reconnects=0, disconnect_debounce_time=0
        )

    @pytest.mark.asyncio
    async def test_starter_survives_unexpected_exception(self, handler, mock_controller):
        """A non-connection exception from controller.start() keeps retrying.

        Previously only a narrow tuple of errors was caught: anything else
        (e.g. a KeyError escaping consumer code) killed the reconnect loop
        permanently and silently.
        """
        calls = 0

        async def buggy_then_ok():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise KeyError("unexpected bug")

        mock_controller.start = buggy_then_ok

        task = asyncio.create_task(handler._starter())
        await asyncio.wait_for(task, 1)

        assert calls == 2
        assert handler.connected is True
        await handler.astop()

    @pytest.mark.asyncio
    async def test_start_propagates_unexpected_first_attempt_error(self, handler, mock_controller):
        """An unexpected first-attempt failure must not report success.

        Previously only selected exception types were recorded; anything else
        made start() return as if connected.
        """
        release = asyncio.Event()
        calls = 0

        async def buggy_start():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise KeyError("unexpected bug")
            await release.wait()

        mock_controller.start = buggy_start

        with pytest.raises(KeyError):
            await handler.start()
        assert handler.connected is False

        release.set()
        await handler.astop()

    @pytest.mark.asyncio
    async def test_concurrent_start_awaits_shared_attempt(self, handler, mock_controller):
        """A concurrent start() awaits the shared first attempt.

        Previously a second start() returned immediately (false success) while
        the first attempt was still connecting.
        """
        release = asyncio.Event()
        started_calls = 0

        async def blocking_start():
            nonlocal started_calls
            started_calls += 1
            await release.wait()

        mock_controller.start = blocking_start

        first = asyncio.create_task(handler.start())
        await asyncio.sleep(0.01)
        second = asyncio.create_task(handler.start())
        await asyncio.sleep(0.01)

        assert not first.done()
        assert not second.done(), "second start() must await the shared attempt"

        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        assert started_calls == 1
        assert handler.connected is True

        await handler.astop()

    @pytest.mark.asyncio
    async def test_cancelled_first_attempt_does_not_report_success(self, handler, mock_controller):
        """stop() during the first attempt cancels start() - never a success."""
        release = asyncio.Event()

        async def blocking_start():
            await release.wait()

        mock_controller.start = blocking_start

        starting = asyncio.create_task(handler.start())
        await asyncio.sleep(0.01)
        handler.stop()

        with pytest.raises(asyncio.CancelledError):
            await starting
        assert handler.connected is False

        await handler.astop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("initial", "expected"),
        [(0, [0, 1, 2, 3]), (1, [1, 2, 3, 4])],
    )
    async def test_backoff_growth_from_degenerate_delays(self, mock_controller, initial, expected):
        """Backoff grows even from 0 and 1.

        Previously min(int(delay * 1.5), MAX) kept a delay of 1 at 1 forever
        and hot-looped a delay of 0.
        """
        handler = ICConnectionHandler(mock_controller, time_between_reconnects=initial)
        mock_controller.start = AsyncMock(side_effect=ICConnectionError("down"))

        delays: list[int] = []
        handler.on_retrying = delays.append

        real_sleep = asyncio.sleep

        async def fast_sleep(delay, *args, **kwargs):
            await real_sleep(0)

        with patch("asyncio.sleep", new=fast_sleep):
            task = asyncio.create_task(handler._starter())
            while len(delays) < 4:
                await real_sleep(0.001)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert delays[:4] == expected


class TestTransactionalStart:
    """Regression tests for issue #62: partial-init failures leak nothing."""

    def _mock_connection(self):
        connection = AsyncMock()
        connection.connected = True
        connection.set_disconnect_callback = MagicMock()
        connection.set_notification_callback = MagicMock()
        return connection

    @staticmethod
    def _system_info_response():
        return {
            "response": "200",
            "objectList": [
                {
                    "objnam": "INCR",
                    "params": {
                        "PROPNAME": "Test Pool",
                        "VER": "1.0.0",
                        "MODE": "ENGLISH",
                        "SNAME": "TestSystem",
                    },
                }
            ],
        }

    @pytest.mark.asyncio
    async def test_base_start_malformed_system_info_closes_connection(self):
        """A malformed system info response closes the socket and raises."""
        controller = ICBaseController("192.168.1.100", 6681)
        connection = self._mock_connection()
        connection.send_request = AsyncMock(return_value={"response": "200"})  # no objectList

        with (
            patch("pyintellicenter.controller.ICConnection", return_value=connection),
            pytest.raises(ICResponseError),
        ):
            await controller.start()

        connection.disconnect.assert_awaited_once()
        assert controller._connection is None

    @pytest.mark.asyncio
    async def test_base_start_request_failure_closes_connection(self):
        """A failure after connect (system info request) closes the socket."""
        controller = ICBaseController("192.168.1.100", 6681)
        connection = self._mock_connection()
        connection.send_request = AsyncMock(side_effect=ICConnectionError("reset"))

        with (
            patch("pyintellicenter.controller.ICConnection", return_value=connection),
            pytest.raises(ICConnectionError),
        ):
            await controller.start()

        connection.disconnect.assert_awaited_once()
        assert controller._connection is None

    @pytest.mark.asyncio
    async def test_model_start_partial_failure_closes_connection(self, monkeypatch):
        """A model-phase failure closes the connection, leaks no tasks.

        The model layer now skips malformed entries instead of raising
        (issue #56), so an unexpected model-load failure is injected directly
        to prove the transactional guarantee for the post-connect phase.
        """
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        connection = self._mock_connection()
        connection.send_request = AsyncMock(
            side_effect=[
                self._system_info_response(),
                {"response": "200", "objectList": []},  # get_all_objects
            ]
        )

        def exploding_add_objects(obj_list):
            raise RuntimeError("unexpected model-load bug")

        monkeypatch.setattr(model, "add_objects", exploding_add_objects)

        with (
            patch("pyintellicenter.controller.ICConnection", return_value=connection),
            pytest.raises(RuntimeError, match="unexpected model-load bug"),
        ):
            await controller.start()

        connection.disconnect.assert_awaited_once()
        assert controller._connection is None
        assert controller._monitor_tasks == set()

    @pytest.mark.asyncio
    async def test_model_start_skips_malformed_object_entries(self):
        """A malformed objectList entry is skipped; start() still succeeds.

        Since issue #56 the model skips entries missing objnam/params instead
        of raising, so a bad entry must not abort startup or close the socket.
        """
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        connection = self._mock_connection()
        connection.send_request = AsyncMock(
            side_effect=[
                self._system_info_response(),
                # get_all_objects: entry missing "objnam" is skipped by the model
                {"response": "200", "objectList": [{"params": {"OBJTYP": "BODY"}}]},
            ]
        )

        with patch("pyintellicenter.controller.ICConnection", return_value=connection):
            await controller.start()

        assert model.num_objects == 0
        assert controller._connection is connection
        connection.disconnect.assert_not_awaited()

        await controller.stop()
        connection.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_model_start_monitoring_batches_never_exceed_limit(self, monkeypatch):
        """start() monitoring batches stay within MAX_ATTRIBUTES_PER_QUERY.

        Previously the flush happened after appending, so a batch could exceed
        the documented maximum by one object's keys.
        """
        from pyintellicenter.controller import MAX_ATTRIBUTES_PER_QUERY

        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        connection = self._mock_connection()

        # 7 objects x 15 keys: the old post-append flush would send a 60-key
        # batch; the pre-check flush must cap every batch at 45.
        crafted = [{"objnam": f"OBJ{i}", "keys": [f"K{j}" for j in range(15)]} for i in range(7)]
        monkeypatch.setattr(model, "attributes_to_track", lambda: crafted)

        batches: list[list[dict]] = []
        system_info_response = self._system_info_response()

        async def scripted_send(cmd, **kwargs):
            if cmd == "GetParamList" and kwargs.get("condition"):
                return system_info_response
            if cmd == "RequestParamList":
                batches.append(kwargs["objectList"])
            return {"response": "200", "objectList": []}

        connection.send_request = AsyncMock(side_effect=scripted_send)

        with patch("pyintellicenter.controller.ICConnection", return_value=connection):
            await controller.start()

        assert batches, "expected monitoring batches to be sent"
        for batch in batches:
            total_keys = sum(len(item["keys"]) for item in batch)
            assert total_keys <= MAX_ATTRIBUTES_PER_QUERY
        covered = [item["objnam"] for batch in batches for item in batch]
        assert covered == [f"OBJ{i}" for i in range(7)]

        await controller.stop()


class TestStartReconcile:
    """Regression tests for issue #68: start() reconciles the model.

    Every (re)connect must prune objects absent from the authoritative
    GetParamList snapshot BEFORE building subscription queries (ghost-equipment
    fix end-to-end), report removals to the consumer as ``{objnam: None}``
    entries, and surface partial snapshots with a WARNING.
    """

    def _mock_connection(self):
        connection = AsyncMock()
        connection.connected = True
        connection.set_disconnect_callback = MagicMock()
        connection.set_notification_callback = MagicMock()
        return connection

    @staticmethod
    def _system_info_response():
        return {
            "response": "200",
            "objectList": [
                {
                    "objnam": "INCR",
                    "params": {
                        "PROPNAME": "Test Pool",
                        "VER": "1.0.0",
                        "MODE": "ENGLISH",
                        "SNAME": "TestSystem",
                    },
                }
            ],
        }

    def _scripted_connection(self, snapshot, batches):
        """Build a mock connection whose GetParamList serves ``snapshot``.

        ``snapshot`` is a one-key dict {"objects": [...]} so tests can swap the
        served object list between start() calls (simulating a reconnect after
        equipment was deleted at the panel). RequestParamList batches are
        appended to ``batches``.
        """
        connection = self._mock_connection()
        system_info_response = self._system_info_response()

        async def scripted_send(cmd, **kwargs):
            if cmd == "GetParamList" and kwargs.get("condition"):
                return system_info_response
            if cmd == "GetParamList":
                return {"response": "200", "objectList": snapshot["objects"]}
            if cmd == "RequestParamList":
                batches.append(kwargs["objectList"])
            return {"response": "200", "objectList": []}

        connection.send_request = AsyncMock(side_effect=scripted_send)
        return connection

    @pytest.mark.asyncio
    async def test_reconnect_prunes_deleted_object(self, caplog):
        """A reconnect snapshot missing an object prunes it end-to-end.

        The ghost is removed from the model, the removal is reported to the
        updated callback as {objnam: None}, it is not re-subscribed, and the
        removal is logged at INFO.
        """
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        snapshot = {
            "objects": [
                {
                    "objnam": "POOL1",
                    "params": {"OBJTYP": "BODY", "SUBTYP": "POOL", "SNAME": "Pool"},
                },
                {
                    "objnam": "C001",
                    "params": {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"},
                },
            ]
        }
        batches: list[list[dict]] = []
        connection = self._scripted_connection(snapshot, batches)

        received: list[dict] = []
        controller.set_updated_callback(lambda ctrl, updates: received.append(dict(updates)))

        with patch("pyintellicenter.controller.ICConnection", return_value=connection):
            await controller.start()
            assert model["C001"] is not None

            # Equipment deleted at the panel: absent from the next snapshot.
            snapshot["objects"] = snapshot["objects"][:1]
            batches.clear()
            received.clear()
            with caplog.at_level(logging.INFO, logger="pyintellicenter.controller"):
                await controller.start()

        # Ghost pruned from the model; surviving object retained.
        assert model["C001"] is None
        assert model["POOL1"] is not None

        # Removal reported to the consumer with the {objnam: None} convention.
        removal_payloads = [u for u in received if "C001" in u]
        assert removal_payloads, "expected the removal to reach the updated callback"
        assert all(u["C001"] is None for u in removal_payloads)

        # No re-subscription for the ghost; the survivor is still subscribed.
        targeted = {item["objnam"] for batch in batches for item in batch}
        assert "C001" not in targeted
        assert "POOL1" in targeted

        # Removal logged at INFO.
        removal_logs = [
            r for r in caplog.records if r.levelno == logging.INFO and "C001" in r.getMessage()
        ]
        assert removal_logs, "expected an INFO log naming the removed object"

        await controller.stop()

    @pytest.mark.asyncio
    async def test_reconcile_runs_before_subscription_queries(self):
        """Ghosts already in the model never appear in tracking queries.

        A model reused across connections may hold stale objects before the
        first start(); pruning must happen before attributes_to_track() is
        consulted so the very first subscription pass is already clean.
        """
        model = PoolModel()
        model.add_object("GHOST1", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Old Light"})
        controller = ICModelController("192.168.1.100", model, 6681)
        snapshot = {
            "objects": [
                {
                    "objnam": "POOL1",
                    "params": {"OBJTYP": "BODY", "SUBTYP": "POOL", "SNAME": "Pool"},
                },
            ]
        }
        batches: list[list[dict]] = []
        connection = self._scripted_connection(snapshot, batches)

        with patch("pyintellicenter.controller.ICConnection", return_value=connection):
            await controller.start()

        assert model["GHOST1"] is None
        targeted = {item["objnam"] for batch in batches for item in batch}
        assert "GHOST1" not in targeted
        assert targeted == {"POOL1"}

        await controller.stop()

    @pytest.mark.asyncio
    async def test_removal_callback_exception_does_not_abort_start(self):
        """A consumer callback raising on a removal must not fail start()."""
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        snapshot = {
            "objects": [
                {
                    "objnam": "POOL1",
                    "params": {"OBJTYP": "BODY", "SUBTYP": "POOL", "SNAME": "Pool"},
                },
                {
                    "objnam": "C001",
                    "params": {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Light"},
                },
            ]
        }
        batches: list[list[dict]] = []
        connection = self._scripted_connection(snapshot, batches)

        def exploding_callback(ctrl, updates):
            raise RuntimeError("consumer bug")

        controller.set_updated_callback(exploding_callback)

        with patch("pyintellicenter.controller.ICConnection", return_value=connection):
            await controller.start()
            snapshot["objects"] = snapshot["objects"][:1]
            batches.clear()
            await controller.start()  # must not raise

        assert model["C001"] is None
        # Startup completed: subscriptions were still requested after the raise.
        assert batches, "expected subscription queries despite the callback raise"

        await controller.stop()

    @pytest.mark.asyncio
    async def test_partial_snapshot_counts_logged_at_info_not_warning(self, caplog):
        """Expected snapshot skips surface as INFO counts, never a WARNING.

        Entries without OBJTYP (firmware 3.008+ pruning artifacts like _FDR)
        or with an untracked type are deliberately DEBUG-only in
        PoolModel.add_objects() (#78); the controller must not double-report
        or escalate them. It reports the ingested/snapshot counts at INFO
        based on the add_objects() return value.
        """
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        snapshot = {
            "objects": [
                {
                    "objnam": "POOL1",
                    "params": {"OBJTYP": "BODY", "SUBTYP": "POOL", "SNAME": "Pool"},
                },
                # Pruned-away params (no OBJTYP): expected, skipped by add_objects.
                {"objnam": "_FDR", "params": {}},
                # Untracked object type: expected, skipped by add_objects.
                {"objnam": "X001", "params": {"OBJTYP": "NOTATYPE", "SNAME": "Mystery"}},
            ]
        }
        batches: list[list[dict]] = []
        connection = self._scripted_connection(snapshot, batches)

        with (
            patch("pyintellicenter.controller.ICConnection", return_value=connection),
            caplog.at_level(logging.INFO, logger="pyintellicenter"),
        ):
            await controller.start()

        assert model.num_objects == 1
        # No WARNING from controller or model for these expected skips.
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
        # The controller INFO line carries the ingested/snapshot counts.
        info_counts = [
            r
            for r in caplog.records
            if r.name == "pyintellicenter.controller"
            and r.levelno == logging.INFO
            and "1 of 3 snapshot entries ingested" in r.getMessage()
        ]
        assert info_counts, "expected an INFO log with the ingested (1) and snapshot (3) counts"

        await controller.stop()

    @pytest.mark.asyncio
    async def test_malformed_snapshot_entry_warns_once_via_model(self, caplog):
        """A malformed entry is warned about by the model only - no duplicate.

        PoolModel.add_objects() (#78) already emits one WARNING with per-call
        counts for malformed entries; the controller must not add a second,
        conflicting warning of its own.
        """
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        snapshot = {
            "objects": [
                {
                    "objnam": "POOL1",
                    "params": {"OBJTYP": "BODY", "SUBTYP": "POOL", "SNAME": "Pool"},
                },
                # Malformed: params is not a dict.
                {"objnam": "BROKEN", "params": "nope"},
            ]
        }
        batches: list[list[dict]] = []
        connection = self._scripted_connection(snapshot, batches)

        with (
            patch("pyintellicenter.controller.ICConnection", return_value=connection),
            caplog.at_level(logging.WARNING, logger="pyintellicenter"),
        ):
            await controller.start()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, "expected exactly one WARNING (from the model)"
        assert warnings[0].name == "pyintellicenter.model"

        await controller.stop()

    @pytest.mark.asyncio
    async def test_full_snapshot_no_removals_no_warning(self, caplog):
        """A clean snapshot produces no removals and no WARNING.

        Includes a duplicate valid entry: duplicates must not be treated as a
        partial snapshot (the old cardinality check false-positived on them).
        """
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model, 6681)
        pool_entry = {
            "objnam": "POOL1",
            "params": {"OBJTYP": "BODY", "SUBTYP": "POOL", "SNAME": "Pool"},
        }
        snapshot = {"objects": [pool_entry, dict(pool_entry)]}
        batches: list[list[dict]] = []
        connection = self._scripted_connection(snapshot, batches)

        received: list[dict] = []
        controller.set_updated_callback(lambda ctrl, updates: received.append(dict(updates)))

        with (
            patch("pyintellicenter.controller.ICConnection", return_value=connection),
            caplog.at_level(logging.WARNING, logger="pyintellicenter"),
        ):
            await controller.start()
            await controller.start()  # reconnect with an identical snapshot

        assert model.num_objects == 1
        # No removal payloads: no callback entry ever maps an objnam to None.
        assert all(value is not None for updates in received for value in updates.values())
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

        await controller.stop()


class TestCoalescedFlushResilience:
    """Regression tests for issue #63: no stranded peer futures."""

    @pytest.fixture
    def controller(self):
        """Create an ICModelController with a mock connection."""
        ctrl = ICModelController("192.168.1.100", PoolModel(), 6681)
        ctrl._connection = MagicMock()
        ctrl._connection.connected = True
        ctrl._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )
        return ctrl

    @pytest.mark.asyncio
    async def test_unexpected_flush_exception_resolves_all_peer_futures(self, controller):
        """A non-ICError flush failure reaches every waiter - nobody hangs.

        Previously only (ICError, OSError) were fanned out; any other
        exception escaped the flush owner and left peer futures pending
        forever.
        """

        async def exploding_send(*args, **kwargs):
            raise RuntimeError("bug in transport layer")

        controller._connection.send_request = exploding_send

        await controller._coalesce_lock.acquire()
        owner = asyncio.create_task(controller.set_circuit_state("C001", True))
        peer_one = asyncio.create_task(controller.set_circuit_state("C002", True))
        peer_two = asyncio.create_task(controller.set_circuit_state("C003", True))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        controller._coalesce_lock.release()

        results = await asyncio.wait_for(
            asyncio.gather(owner, peer_one, peer_two, return_exceptions=True), timeout=1
        )
        assert all(isinstance(result, RuntimeError) for result in results)
        assert controller._pending_requests == []
        assert controller._pending_changes == {}


class TestSubscriptions:
    """Test the per-object subscription API (issue #66)."""

    @pytest.fixture
    def model(self):
        """Create a PoolModel instance."""
        return PoolModel()

    @pytest.fixture
    def controller(self, model):
        """Create an ICModelController with two circuits in the model."""
        controller = ICModelController("192.168.1.100", model, 6681)
        model.add_object(
            "C0001",
            {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT", "SNAME": "Pool Light", "STATUS": "OFF"},
        )
        model.add_object(
            "C0002",
            {"OBJTYP": "CIRCUIT", "SUBTYP": "GENERIC", "SNAME": "Cleaner", "STATUS": "OFF"},
        )
        return controller

    def _notify(self, controller, objnam, attrs):
        """Push a NotifyList for one object through the real dispatch path."""
        controller._on_notification(
            {"command": "NotifyList", "objectList": [{"objnam": objnam, "params": attrs}]}
        )

    def test_per_objnam_subscriber_receives_only_its_changes(self, controller):
        """A per-objnam subscriber sees only its object's entry, as a mapping."""
        received = []
        controller.subscribe("C0001", lambda ctrl, changes: received.append(dict(changes)))

        self._notify(controller, "C0002", {"STATUS": "ON"})
        assert received == []

        self._notify(controller, "C0001", {"STATUS": "ON"})
        assert received == [{"C0001": {"STATUS": "ON"}}]

    def test_per_objnam_subscriber_gets_controller_argument(self, controller):
        """The first callback argument is the controller (matches legacy signature)."""
        seen = []
        controller.subscribe("C0001", lambda ctrl, changes: seen.append(ctrl))
        self._notify(controller, "C0001", {"STATUS": "ON"})
        assert seen == [controller]

    def test_per_objnam_subscriber_receives_removal_none(self, controller):
        """Removal is delivered as {objnam: None} per the PR #81 contract."""
        received = []
        controller.subscribe("C0001", lambda ctrl, changes: received.append(dict(changes)))

        controller._notify_updated({"C0001": None})
        assert received == [{"C0001": None}]

    def test_none_objnam_subscriber_receives_all_updates(self, controller):
        """An all-object subscriber receives the full update mapping."""
        received = []
        controller.subscribe(None, lambda ctrl, changes: received.append(dict(changes)))

        self._notify(controller, "C0001", {"STATUS": "ON"})
        self._notify(controller, "C0002", {"STATUS": "ON"})

        assert received == [{"C0001": {"STATUS": "ON"}}, {"C0002": {"STATUS": "ON"}}]

    def test_multiple_subscribers_same_objnam(self, controller):
        """Multiple subscribers for the same objnam all fire, in order."""
        order = []
        controller.subscribe("C0001", lambda ctrl, changes: order.append("first"))
        controller.subscribe("C0001", lambda ctrl, changes: order.append("second"))

        self._notify(controller, "C0001", {"STATUS": "ON"})
        assert order == ["first", "second"]

    def test_unsubscribe_stops_delivery(self, controller):
        """Calling the remover stops delivery; calling it again is a no-op."""
        received = []
        unsubscribe = controller.subscribe(
            "C0001", lambda ctrl, changes: received.append(dict(changes))
        )

        self._notify(controller, "C0001", {"STATUS": "ON"})
        assert len(received) == 1

        unsubscribe()
        self._notify(controller, "C0001", {"STATUS": "OFF"})
        assert len(received) == 1

        # Idempotent, and empty listener lists are pruned.
        unsubscribe()
        assert controller._subscriptions == {}

    def test_unsubscribe_idempotent_with_duplicate_callback(self, controller):
        """A remover called twice must not remove a peer's identical callback."""
        received = []

        def cb(ctrl, changes):
            received.append(dict(changes))

        remove_first = controller.subscribe("C0001", cb)
        controller.subscribe("C0001", cb)

        remove_first()
        remove_first()  # must not remove the second registration

        self._notify(controller, "C0001", {"STATUS": "ON"})
        assert len(received) == 1

    def test_unsubscribe_during_dispatch_is_safe(self, controller):
        """A subscriber removing itself (or a peer) mid-dispatch does not break dispatch."""
        received = []
        removers = {}

        def self_removing(ctrl, changes):
            received.append("self_removing")
            removers["self"]()

        def peer(ctrl, changes):
            received.append("peer")

        removers["self"] = controller.subscribe("C0001", self_removing)
        controller.subscribe("C0001", peer)

        self._notify(controller, "C0001", {"STATUS": "ON"})
        assert received == ["self_removing", "peer"]

        # The self-removed subscriber gets no further updates.
        self._notify(controller, "C0001", {"STATUS": "OFF"})
        assert received == ["self_removing", "peer", "peer"]

    def test_subscriber_exception_does_not_affect_others_or_legacy(self, controller, caplog):
        """One subscriber raising never breaks peers, the legacy callback, or dispatch."""
        legacy = []
        controller.set_updated_callback(lambda ctrl, updates: legacy.append(dict(updates)))

        survivors = []

        def exploding(ctrl, changes):
            raise RuntimeError("boom")

        controller.subscribe(None, exploding)
        controller.subscribe("C0001", exploding)
        controller.subscribe("C0001", lambda ctrl, changes: survivors.append(dict(changes)))

        with caplog.at_level(logging.ERROR):
            self._notify(controller, "C0001", {"STATUS": "ON"})

        assert legacy == [{"C0001": {"STATUS": "ON"}}]
        assert survivors == [{"C0001": {"STATUS": "ON"}}]
        assert "Error in model update subscriber" in caplog.text

    def test_legacy_callback_exception_does_not_affect_subscribers(self, controller, caplog):
        """The legacy callback raising never blocks subscription dispatch."""

        def exploding(ctrl, updates):
            raise RuntimeError("legacy boom")

        controller.set_updated_callback(exploding)
        received = []
        controller.subscribe("C0001", lambda ctrl, changes: received.append(dict(changes)))

        with caplog.at_level(logging.ERROR):
            self._notify(controller, "C0001", {"STATUS": "ON"})

        assert received == [{"C0001": {"STATUS": "ON"}}]

    def test_legacy_callback_fires_before_subscribers(self, controller):
        """Ordering: legacy updated callback first, then subscribers."""
        order = []
        controller.set_updated_callback(lambda ctrl, updates: order.append("legacy"))
        controller.subscribe(None, lambda ctrl, changes: order.append("all"))
        controller.subscribe("C0001", lambda ctrl, changes: order.append("per-object"))

        self._notify(controller, "C0001", {"STATUS": "ON"})
        assert order == ["legacy", "all", "per-object"]

    def test_empty_updates_do_not_dispatch(self, controller):
        """Empty update mappings are not dispatched to anyone."""
        received = []
        controller.subscribe(None, lambda ctrl, changes: received.append(dict(changes)))
        controller._notify_updated({})
        assert received == []

    def test_handler_subscribe_forwards_to_controller(self, controller):
        """ICConnectionHandler.subscribe forwards to the managed controller."""
        handler = ICConnectionHandler(controller)
        legacy = []
        handler.on_updated = lambda ctrl, updates: legacy.append(dict(updates))

        received = []
        unsubscribe = handler.subscribe(
            "C0001", lambda ctrl, changes: received.append(dict(changes))
        )

        self._notify(controller, "C0001", {"STATUS": "ON"})
        # Handler's claimed slot (on_updated) still works unchanged...
        assert legacy == [{"C0001": {"STATUS": "ON"}}]
        # ...and the forwarded subscription delivers per-object entries.
        assert received == [{"C0001": {"STATUS": "ON"}}]

        unsubscribe()
        self._notify(controller, "C0001", {"STATUS": "OFF"})
        assert len(received) == 1

    def test_handler_subscribe_requires_model_controller(self):
        """Handler subscribe raises TypeError for a non-model controller."""
        base = ICBaseController("192.168.1.100", 6681)
        handler = ICConnectionHandler(base)
        with pytest.raises(TypeError, match="ICModelController"):
            handler.subscribe("C0001", lambda ctrl, changes: None)
