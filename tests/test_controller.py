"""Tests for pyintellicenter controller module."""

import asyncio
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
        """Test set_cover_state convenience method."""
        controller._connection = MagicMock()
        controller._connection.connected = True
        controller._connection.send_request = AsyncMock(
            return_value={"response": "200", "objectList": []}
        )

        model.add_object(
            "CVR01",
            {"OBJTYP": "EXTINSTR", "SUBTYP": "COVER", "SNAME": "Pool Cover", "STATUS": "OFF"},
        )

        await controller.set_cover_state("CVR01", True)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["objnam"] == "CVR01"
        assert call_args[1]["objectList"][0]["params"]["STATUS"] == "ON"

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
            {"OBJTYP": "EXTINSTR", "SUBTYP": "COVER", "SNAME": "Pool Cover", "STATUS": "ON"},
        )

        await controller.set_cover_state("CVR01", False)

        call_args = controller._connection.send_request.call_args
        assert call_args[1]["objectList"][0]["params"]["STATUS"] == "OFF"

    def test_is_cover_on(self, controller, model):
        """Test is_cover_on helper method."""
        model.add_object(
            "CVR01",
            {"OBJTYP": "EXTINSTR", "SUBTYP": "COVER", "SNAME": "Pool Cover", "STATUS": "ON"},
        )
        model.add_object(
            "CVR02",
            {"OBJTYP": "EXTINSTR", "SUBTYP": "COVER", "SNAME": "Spa Cover", "STATUS": "OFF"},
        )

        assert controller.is_cover_on("CVR01") is True
        assert controller.is_cover_on("CVR02") is False
        assert controller.is_cover_on("NONEXISTENT") is False

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
        """Test get_circuit_groups returns all circuit group objects."""
        model.add_object("CG001", {"OBJTYP": "CIRCGRP", "SNAME": "Light Group 1"})
        model.add_object("CG002", {"OBJTYP": "CIRCGRP", "SNAME": "Light Group 2"})
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Light"})

        groups = controller.get_circuit_groups()

        assert len(groups) == 2
        assert all(obj.objtype == "CIRCGRP" for obj in groups)

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
        # Create circuit groups
        model.add_object(
            "CG001",
            {"OBJTYP": "CIRCGRP", "SNAME": "Color Group", "CIRCUIT": "C001"},
        )
        model.add_object(
            "CG002",
            {"OBJTYP": "CIRCGRP", "SNAME": "Non-Color Group", "CIRCUIT": "C002"},
        )
        model.add_object("CG003", {"OBJTYP": "CIRCGRP", "SNAME": "Empty Group"})

        color_groups = controller.get_color_light_groups()

        assert len(color_groups) == 1
        assert color_groups[0].objnam == "CG001"

    def test_get_all_entities_includes_circuit_groups(self, controller, model):
        """Test get_all_entities includes circuit_groups and color_light_groups."""
        # Create color light
        model.add_object("C001", {"OBJTYP": "CIRCUIT", "SUBTYP": "INTELLI", "SNAME": "Pool Light"})
        # Create circuit group with color light
        model.add_object(
            "CG001",
            {"OBJTYP": "CIRCGRP", "SNAME": "Color Group", "CIRCUIT": "C001"},
        )

        entities = controller.get_all_entities()

        assert "circuit_groups" in entities
        assert "color_light_groups" in entities
        assert len(entities["circuit_groups"]) == 1
        assert len(entities["color_light_groups"]) == 1


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
        """Test circuit breaker opens after repeated failures."""
        from pyintellicenter.controller import CIRCUIT_BREAKER_FAILURES

        handler = ICConnectionHandler(mock_controller, time_between_reconnects=0)
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ICConnectionError("Connection failed")

        mock_controller.start = always_fail

        # First attempt will fail and raise, but reconnection continues in background
        with pytest.raises(ICConnectionError):
            await handler.start()

        # Allow time for failures to accumulate (short delay between retries)
        await asyncio.sleep(0.5)

        handler.stop()

        # Should have triggered circuit breaker
        assert (
            handler._failure_count >= CIRCUIT_BREAKER_FAILURES
            or call_count >= CIRCUIT_BREAKER_FAILURES
        )

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

        await asyncio.sleep(0.5)

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
