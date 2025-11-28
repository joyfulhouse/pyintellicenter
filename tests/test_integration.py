"""Integration tests for pyintellicenter using mock server.

These tests verify the full flow of communication between the library
and an IntelliCenter system using a mock server.
"""

import asyncio

import pytest

from pyintellicenter import (
    HeaterType,
    ICBaseController,
    ICConnection,
    ICConnectionHandler,
    ICModelController,
    PoolModel,
)
from tests.mock_server import MockIntelliCenterServer


class TestICConnectionIntegration:
    """Integration tests for ICConnection."""

    @pytest.fixture
    async def server(self):
        """Create and start mock server."""
        async with MockIntelliCenterServer() as server:
            server.add_object("POOL1", "BODY", "POOL", "Pool", STATUS="OFF")
            server.add_object("SPA1", "BODY", "SPA", "Spa", STATUS="OFF")
            server.add_object("LIGHT1", "CIRCUIT", "LIGHT", "Pool Light", STATUS="OFF")
            yield server

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, server):
        """Test basic connection and disconnection."""
        conn = ICConnection(server.host, server.port)

        await conn.connect()
        assert conn.connected is True

        await conn.disconnect()
        assert conn.connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self, server):
        """Test connection as context manager."""
        async with ICConnection(server.host, server.port) as conn:
            assert conn.connected is True

    @pytest.mark.asyncio
    async def test_get_param_list(self, server):
        """Test GetParamList request."""
        async with ICConnection(server.host, server.port) as conn:
            response = await conn.send_request(
                "GetParamList",
                condition="",
                objectList=[{"objnam": "INCR", "keys": ["OBJTYP", "SUBTYP", "SNAME"]}],
            )
            assert response["response"] == "200"
            assert len(response["objectList"]) > 0

    @pytest.mark.asyncio
    async def test_set_param_list(self, server):
        """Test SETPARAMLIST request."""
        async with ICConnection(server.host, server.port) as conn:
            response = await conn.send_request(
                "SETPARAMLIST",
                objectList=[{"objnam": "LIGHT1", "params": {"STATUS": "ON"}}],
            )
            assert response["response"] == "200"

            # Verify the change was applied
            obj = server.get_object("LIGHT1")
            assert obj is not None
            assert obj["STATUS"] == "ON"

    @pytest.mark.asyncio
    async def test_notification_callback(self, server):
        """Test notification callback is called during request processing.

        Notifications are processed via queue during send_request() calls, so we
        configure the server to send a notification before responding.
        """
        received_notifications: list[dict] = []

        def on_notification(msg: dict) -> None:
            received_notifications.append(msg)

        # Set callback BEFORE connecting so the notification queue is initialized
        conn = ICConnection(server.host, server.port)
        conn.set_notification_callback(on_notification)

        async with conn:
            # Configure server to send notification before responding
            original_handler = server._handlers["GetParamList"]

            async def handler_with_notification(msg: dict) -> dict:
                # Send notification first
                await server.send_notification([{"objnam": "POOL1", "params": {"TEMP": "80"}}])
                # Small delay to ensure notification is sent
                await asyncio.sleep(0.01)
                # Then return normal response
                return await original_handler(msg)

            server._handlers["GetParamList"] = handler_with_notification

            # Make request - notification should be received during processing
            await conn.send_request(
                "GetParamList",
                condition="",
                objectList=[{"objnam": "INCR", "keys": ["OBJTYP"]}],
            )

            # Restore original handler
            server._handlers["GetParamList"] = original_handler

            # Allow queue consumer to process the notification
            await asyncio.sleep(0.02)

            # Verify notification was received
            assert len(received_notifications) == 1
            assert received_notifications[0]["command"] == "NotifyList"
            assert received_notifications[0]["objectList"][0]["objnam"] == "POOL1"


class TestICBaseControllerIntegration:
    """Integration tests for ICBaseController."""

    @pytest.fixture
    async def server(self):
        """Create and start mock server."""
        async with MockIntelliCenterServer() as server:
            server.set_system_info("Integration Test Pool", "2.0.0")
            server.add_object("POOL1", "BODY", "POOL", "Pool", STATUS="OFF", LOTMP="82")
            server.add_object("LIGHT1", "CIRCUIT", "LIGHT", "Pool Light", STATUS="OFF")
            yield server

    @pytest.mark.asyncio
    async def test_start_and_stop(self, server):
        """Test controller start and stop."""
        controller = ICBaseController(server.host, server.port)

        await controller.start()
        assert controller.connected is True
        assert controller.system_info is not None
        assert controller.system_info.sw_version == "2.0.0"

        await controller.stop()
        assert controller.connected is False

    @pytest.mark.asyncio
    async def test_request_changes(self, server):
        """Test request_changes method."""
        controller = ICBaseController(server.host, server.port)

        await controller.start()
        try:
            response = await controller.request_changes("LIGHT1", {"STATUS": "ON"})
            assert response["response"] == "200"

            # Verify change was applied
            obj = server.get_object("LIGHT1")
            assert obj is not None
            assert obj["STATUS"] == "ON"
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_all_objects(self, server):
        """Test get_all_objects method."""
        controller = ICBaseController(server.host, server.port)

        await controller.start()
        try:
            objects = await controller.get_all_objects(["OBJTYP", "SUBTYP", "SNAME"])
            assert len(objects) >= 2  # At least POOL1 and LIGHT1
        finally:
            await controller.stop()


class TestICModelControllerIntegration:
    """Integration tests for ICModelController."""

    @pytest.fixture
    async def server(self):
        """Create and start mock server."""
        async with MockIntelliCenterServer() as server:
            server.set_system_info("Model Test Pool", "2.0.0")
            server.add_object(
                "POOL1", "BODY", "POOL", "Pool", STATUS="OFF", LOTMP="82", TEMP="78", MODE="1"
            )
            server.add_object(
                "SPA1", "BODY", "SPA", "Spa", STATUS="OFF", LOTMP="102", TEMP="100", MODE="0"
            )
            server.add_object("LIGHT1", "CIRCUIT", "LIGHT", "Pool Light", STATUS="OFF")
            server.add_object("PUMP1", "PUMP", "SPEED", "Main Pump", STATUS="4", RPM="0")
            server.add_object(
                "HEATER1", "HEATER", "GENERIC", "Pool Heater", STATUS="OFF", HEATING="OFF"
            )
            server.add_object("SCHED1", "SCHED", "SCHED", "Morning Schedule", STATUS="OFF")
            server.add_object("SENSE1", "SENSE", "POOL", "Pool Temp Sensor", SOURCE="78")
            server.add_object("CHEM1", "CHEM", "ICHLOR", "IntelliChlor", SUPER="OFF", SALT="3200")
            yield server

    @pytest.mark.asyncio
    async def test_start_populates_model(self, server):
        """Test that starting controller populates the model."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            # Model should have objects
            assert model.num_objects >= 1
            # Get bodies should find our pool and spa
            bodies = controller.get_bodies()
            body_names = {b.sname for b in bodies}
            assert "Pool" in body_names or "Spa" in body_names
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_set_circuit_state(self, server):
        """Test set_circuit_state convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            await controller.set_circuit_state("LIGHT1", True)

            # Verify change on server
            obj = server.get_object("LIGHT1")
            assert obj is not None
            assert obj["STATUS"] == "ON"
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_set_heat_mode(self, server):
        """Test set_heat_mode convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            await controller.set_heat_mode("POOL1", HeaterType.HEATER)

            obj = server.get_object("POOL1")
            assert obj is not None
            assert obj["MODE"] == "2"
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_set_setpoint(self, server):
        """Test set_setpoint convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            await controller.set_setpoint("SPA1", 104)

            obj = server.get_object("SPA1")
            assert obj is not None
            assert obj["LOTMP"] == "104"
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_set_super_chlorinate(self, server):
        """Test set_super_chlorinate convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            await controller.set_super_chlorinate("CHEM1", True)

            obj = server.get_object("CHEM1")
            assert obj is not None
            assert obj["SUPER"] == "ON"
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_bodies(self, server):
        """Test get_bodies convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            bodies = controller.get_bodies()
            assert len(bodies) == 2
            names = {b.sname for b in bodies}
            assert "Pool" in names
            assert "Spa" in names
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_heaters(self, server):
        """Test get_heaters convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            heaters = controller.get_heaters()
            assert len(heaters) == 1
            assert heaters[0].sname == "Pool Heater"
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_schedules(self, server):
        """Test get_schedules convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            schedules = controller.get_schedules()
            assert len(schedules) == 1
            assert schedules[0].sname == "Morning Schedule"
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_sensors(self, server):
        """Test get_sensors convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            sensors = controller.get_sensors()
            assert len(sensors) == 1
            assert sensors[0].sname == "Pool Temp Sensor"
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_notification_updates_model(self, server):
        """Test that notifications update the model during request processing.

        Notifications are processed during send_request() calls, so we
        configure the server to send a notification before responding to
        a subsequent request.
        """
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            # Verify initial value
            pool = model["POOL1"]
            assert pool["TEMP"] == "78"

            # Track model updates
            updates_received: list[dict] = []

            def on_updated(ctrl: ICModelController, updates: dict) -> None:
                updates_received.append(updates)

            controller.set_updated_callback(on_updated)

            # Configure server to send notification before responding
            original_handler = server._handlers["GetParamList"]

            async def handler_with_notification(msg: dict) -> dict:
                # Update server state
                server.update_object("POOL1", TEMP="85")
                # Send notification about the update
                await server.send_notification([{"objnam": "POOL1", "params": {"TEMP": "85"}}])
                await asyncio.sleep(0.01)
                return await original_handler(msg)

            server._handlers["GetParamList"] = handler_with_notification

            # Make a request - notification will be received and processed
            await controller.send_cmd(
                "GetParamList",
                {"condition": "", "objectList": [{"objnam": "INCR", "keys": ["OBJTYP"]}]},
            )

            # Restore handler
            server._handlers["GetParamList"] = original_handler

            # Allow notification queue consumer to process
            await asyncio.sleep(0.02)

            # Model should be updated
            assert pool["TEMP"] == "85"
            assert len(updates_received) >= 1
            assert "POOL1" in updates_received[-1]
        finally:
            await controller.stop()


class TestICConnectionHandlerIntegration:
    """Integration tests for ICConnectionHandler."""

    @pytest.fixture
    async def server(self):
        """Create and start mock server."""
        async with MockIntelliCenterServer() as server:
            server.set_system_info("Handler Test Pool", "2.0.0")
            server.add_object("POOL1", "BODY", "POOL", "Pool", STATUS="OFF")
            yield server

    @pytest.mark.asyncio
    async def test_handler_connects(self, server):
        """Test handler connects successfully."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)
        handler = ICConnectionHandler(controller, time_between_reconnects=1)

        started_event = asyncio.Event()

        def on_started(ctrl: ICBaseController) -> None:
            started_event.set()

        handler.on_started = on_started

        await handler.start()
        try:
            # Wait for connection
            await asyncio.wait_for(started_event.wait(), timeout=5.0)
            assert controller.connected is True
        finally:
            handler.stop()
            await asyncio.sleep(0.1)  # Allow cleanup

    @pytest.mark.asyncio
    async def test_handler_reconnects(self):
        """Test handler reconnects after simulated disconnect.

        This test verifies the ICConnectionHandler's reconnection logic
        by directly triggering the disconnect callback, which simulates
        what would happen when the keepalive detects a connection loss.
        """
        # Start server
        server = MockIntelliCenterServer(port=0)
        await server.start()
        port = server.port

        server.set_system_info("Reconnect Test Pool", "2.0.0")
        server.add_object("POOL1", "BODY", "POOL", "Pool", STATUS="OFF")

        model = PoolModel()
        controller = ICModelController(server.host, model, port)
        handler = ICConnectionHandler(controller, time_between_reconnects=1)

        started_event = asyncio.Event()
        reconnected_event = asyncio.Event()

        def on_started(ctrl: ICBaseController) -> None:
            started_event.set()

        def on_reconnected(ctrl: ICBaseController) -> None:
            reconnected_event.set()

        handler.on_started = on_started
        handler.on_reconnected = on_reconnected

        await handler.start()
        try:
            # Wait for initial connection
            await asyncio.wait_for(started_event.wait(), timeout=5.0)
            assert controller.connected is True

            # Manually disconnect and trigger reconnect
            # This simulates what happens when keepalive detects connection loss
            await controller.stop()

            # Trigger the disconnect handler directly - this starts reconnection
            handler._on_disconnect(controller, Exception("Simulated disconnect"))

            # Wait for reconnection
            await asyncio.wait_for(reconnected_event.wait(), timeout=10.0)
            assert controller.connected is True
        finally:
            handler.stop()
            await server.stop()
            await asyncio.sleep(0.1)  # Allow cleanup


class TestICModelControllerNewMethods:
    """Tests for new ICModelController methods."""

    @pytest.fixture
    async def server(self):
        """Create and start mock server with comprehensive objects."""
        async with MockIntelliCenterServer() as server:
            server.set_system_info("Full Test Pool", "2.0.0")
            server.add_object("POOL1", "BODY", "POOL", "Pool", STATUS="OFF", LOTMP="82", TEMP="78")
            server.add_object("LIGHT1", "CIRCUIT", "LIGHT", "Pool Light", STATUS="OFF")
            server.add_object("LIGHT2", "CIRCUIT", "INTELLI", "Spa Light", STATUS="OFF")
            server.add_object("PUMP1", "PUMP", "SPEED", "Main Pump", STATUS="4", RPM="0")
            server.add_object("PUMP2", "PUMP", "VSF", "Booster Pump", STATUS="4", RPM="0")
            server.add_object("CHEM1", "CHEM", "ICHLOR", "IntelliChlor", SUPER="OFF", SALT="3200")
            server.add_object("CHEM2", "CHEM", "ICHEM", "IntelliChem", PHVAL="7.4", ORPVAL="700")
            yield server

    @pytest.mark.asyncio
    async def test_set_multiple_circuit_states_on(self, server):
        """Test setting multiple circuits on simultaneously."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            response = await controller.set_multiple_circuit_states(["LIGHT1", "LIGHT2"], True)
            assert response["response"] == "200"

            # Verify both changed
            assert server.get_object("LIGHT1")["STATUS"] == "ON"
            assert server.get_object("LIGHT2")["STATUS"] == "ON"
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_set_multiple_circuit_states_off(self, server):
        """Test setting multiple circuits off simultaneously."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        # First turn them on
        server.update_object("LIGHT1", STATUS="ON")
        server.update_object("LIGHT2", STATUS="ON")

        await controller.start()
        try:
            response = await controller.set_multiple_circuit_states(["LIGHT1", "LIGHT2"], False)
            assert response["response"] == "200"

            # Verify both changed
            assert server.get_object("LIGHT1")["STATUS"] == "OFF"
            assert server.get_object("LIGHT2")["STATUS"] == "OFF"
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_pumps(self, server):
        """Test get_pumps convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            pumps = controller.get_pumps()
            assert len(pumps) == 2
            names = {p.sname for p in pumps}
            assert "Main Pump" in names
            assert "Booster Pump" in names
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_chem_controllers(self, server):
        """Test get_chem_controllers convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            chem = controller.get_chem_controllers()
            assert len(chem) == 2
            subtypes = {c.subtype for c in chem}
            assert "ICHLOR" in subtypes
            assert "ICHEM" in subtypes
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_configuration(self, server):
        """Test get_configuration convenience method."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            # GetConfiguration returns empty from mock but should not error
            config = await controller.get_configuration()
            assert isinstance(config, list)
        finally:
            await controller.stop()


class TestIntelliChemConfigIntegration:
    """Integration tests for IntelliChem configuration setters (ALK, CALC, CYACID)."""

    @pytest.fixture
    async def server(self):
        """Create and start mock server with IntelliChem controller."""
        async with MockIntelliCenterServer() as server:
            server.set_system_info("Chemistry Test Pool", "2.0.0")
            server.add_object("POOL1", "BODY", "POOL", "Pool", STATUS="OFF")
            # IntelliChem with user-configurable values for Saturation Index calculation
            server.add_object(
                "CHEM1",
                "CHEM",
                "ICHEM",
                "IntelliChem",
                ALK="100",  # Alkalinity (ppm)
                CALC="250",  # Calcium Hardness (ppm)
                CYACID="30",  # Cyanuric Acid (ppm)
                PHVAL="7.4",
                ORPVAL="700",
                PHSET="7.5",
                ORPSET="650",
            )
            yield server

    @pytest.mark.asyncio
    async def test_set_alkalinity(self, server):
        """Test setting alkalinity and resetting to original value."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            # Get original value
            original = server.get_object("CHEM1")["ALK"]

            # Set new value
            response = await controller.set_alkalinity("CHEM1", 120)
            assert response["response"] == "200"
            assert server.get_object("CHEM1")["ALK"] == "120"

            # Reset to original
            await controller.set_alkalinity("CHEM1", int(original))
            assert server.get_object("CHEM1")["ALK"] == original
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_set_alkalinity_invalid_range(self, server):
        """Test that invalid alkalinity values raise ValueError."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            with pytest.raises(ValueError, match="outside valid range"):
                await controller.set_alkalinity("CHEM1", -1)

            with pytest.raises(ValueError, match="outside valid range"):
                await controller.set_alkalinity("CHEM1", 801)
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_set_calcium_hardness(self, server):
        """Test setting calcium hardness and resetting to original value."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            # Get original value
            original = server.get_object("CHEM1")["CALC"]

            # Set new value
            response = await controller.set_calcium_hardness("CHEM1", 350)
            assert response["response"] == "200"
            assert server.get_object("CHEM1")["CALC"] == "350"

            # Reset to original
            await controller.set_calcium_hardness("CHEM1", int(original))
            assert server.get_object("CHEM1")["CALC"] == original
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_set_calcium_hardness_invalid_range(self, server):
        """Test that invalid calcium hardness values raise ValueError."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            with pytest.raises(ValueError, match="outside valid range"):
                await controller.set_calcium_hardness("CHEM1", -1)

            with pytest.raises(ValueError, match="outside valid range"):
                await controller.set_calcium_hardness("CHEM1", 801)
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_set_cyanuric_acid(self, server):
        """Test setting cyanuric acid and resetting to original value."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            # Get original value
            original = server.get_object("CHEM1")["CYACID"]

            # Set new value
            response = await controller.set_cyanuric_acid("CHEM1", 50)
            assert response["response"] == "200"
            assert server.get_object("CHEM1")["CYACID"] == "50"

            # Reset to original
            await controller.set_cyanuric_acid("CHEM1", int(original))
            assert server.get_object("CHEM1")["CYACID"] == original
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_set_cyanuric_acid_invalid_range(self, server):
        """Test that invalid cyanuric acid values raise ValueError."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            with pytest.raises(ValueError, match="outside valid range"):
                await controller.set_cyanuric_acid("CHEM1", -1)

            with pytest.raises(ValueError, match="outside valid range"):
                await controller.set_cyanuric_acid("CHEM1", 201)
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_alkalinity(self, server):
        """Test getting alkalinity value from model."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            alk = controller.get_alkalinity("CHEM1")
            assert alk == 100
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_calcium_hardness(self, server):
        """Test getting calcium hardness value from model."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            calc = controller.get_calcium_hardness("CHEM1")
            assert calc == 250
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_get_cyanuric_acid(self, server):
        """Test getting cyanuric acid value from model."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            cya = controller.get_cyanuric_acid("CHEM1")
            assert cya == 30
        finally:
            await controller.stop()

    @pytest.mark.asyncio
    async def test_chemistry_config_full_workflow(self, server):
        """Test complete workflow of setting all chemistry config values."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            # Store original values
            chem_obj = server.get_object("CHEM1")
            orig_alk = chem_obj["ALK"]
            orig_calc = chem_obj["CALC"]
            orig_cya = chem_obj["CYACID"]

            # Set new values
            await controller.set_alkalinity("CHEM1", 110)
            await controller.set_calcium_hardness("CHEM1", 300)
            await controller.set_cyanuric_acid("CHEM1", 45)

            # Verify changes
            assert server.get_object("CHEM1")["ALK"] == "110"
            assert server.get_object("CHEM1")["CALC"] == "300"
            assert server.get_object("CHEM1")["CYACID"] == "45"

            # Reset to original values
            await controller.set_alkalinity("CHEM1", int(orig_alk))
            await controller.set_calcium_hardness("CHEM1", int(orig_calc))
            await controller.set_cyanuric_acid("CHEM1", int(orig_cya))

            # Verify reset
            assert server.get_object("CHEM1")["ALK"] == orig_alk
            assert server.get_object("CHEM1")["CALC"] == orig_calc
            assert server.get_object("CHEM1")["CYACID"] == orig_cya
        finally:
            await controller.stop()


class TestPoolModelIntegration:
    """Integration tests for PoolModel with real data flow."""

    @pytest.fixture
    async def server(self):
        """Create and start mock server."""
        async with MockIntelliCenterServer() as server:
            server.set_system_info("Full Test Pool", "2.0.0")
            # Add a comprehensive set of objects
            server.add_object(
                "POOL1", "BODY", "POOL", "Pool", STATUS="ON", LOTMP="82", TEMP="78", HTMODE="0"
            )
            server.add_object(
                "SPA1", "BODY", "SPA", "Spa", STATUS="OFF", LOTMP="102", TEMP="100", HTMODE="0"
            )
            server.add_object("FILTER", "CIRCUIT", "GENERIC", "Filter Pump", STATUS="ON")
            server.add_object("POOLLIGHT", "CIRCUIT", "INTELLI", "Pool Light", STATUS="OFF")
            server.add_object("SPALIGHT", "CIRCUIT", "LIGHT", "Spa Light", STATUS="OFF")
            server.add_object("WATERFALL", "CIRCUIT", "GENERIC", "Waterfall", STATUS="OFF")
            yield server

    @pytest.mark.asyncio
    async def test_full_workflow(self, server):
        """Test a complete workflow of connecting, reading, and modifying state."""
        model = PoolModel()
        controller = ICModelController(server.host, model, server.port)

        await controller.start()
        try:
            # Verify initial state
            assert model.num_objects >= 6

            pool = model["POOL1"]
            assert pool.sname == "Pool"
            assert pool["STATUS"] == "ON"

            # Turn on spa
            await controller.set_circuit_state("SPA1", True)
            spa_obj = server.get_object("SPA1")
            assert spa_obj is not None
            assert spa_obj["STATUS"] == "ON"

            # Turn on pool light
            await controller.set_circuit_state("POOLLIGHT", True)
            light_obj = server.get_object("POOLLIGHT")
            assert light_obj is not None
            assert light_obj["STATUS"] == "ON"

            # Set spa temperature
            await controller.set_setpoint("SPA1", 104)
            spa_obj = server.get_object("SPA1")
            assert spa_obj is not None
            assert spa_obj["LOTMP"] == "104"

            # Filter by type
            bodies = controller.get_bodies()
            assert len(bodies) == 2

            circuits = controller.get_circuits()
            assert len(circuits) == 4

        finally:
            await controller.stop()
