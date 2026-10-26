"""Scheduled controller recovery from first-alias-only firmware notifications.

Journeys: callers start a controller, observe telemetry through subscriptions,
then stop/reconnect it; its scheduled reads recover fields absent from pushes.
All servers are local fakes, not physical firmware validation.
"""

import asyncio
import math
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import orjson
import pytest
from websockets.asyncio.server import serve

from pyintellicenter import ICCommandError, ICModelController, PoolModel
from pyintellicenter import controller as controller_module
from pyintellicenter.exceptions import ICTimeoutError
from tests.mock_server import MockIntelliCenterServer


class Clock:
    """Advance only the controller's monotonic scheduler, leaving socket IO real."""

    def __init__(self, monkeypatch):
        self.now = 1000.0
        self.waits = asyncio.Queue()
        self.pending = None
        self.delay = None
        monkeypatch.setattr(controller_module, "time", SimpleNamespace(monotonic=lambda: self.now))
        proxy = SimpleNamespace(**vars(asyncio))
        proxy.sleep = self.sleep
        monkeypatch.setattr(controller_module, "asyncio", proxy)

    async def sleep(self, delay):
        if asyncio.current_task().get_name() != "intellicenter-telemetry-reconcile":
            await asyncio.sleep(delay)
            return
        future = asyncio.Future()
        await self.waits.put((delay, future))
        await future

    async def paused(self):
        self.delay, self.pending = await asyncio.wait_for(self.waits.get(), 3)
        return self.delay

    def advance(self, extra=0):
        self.now += self.delay + extra
        self.pending.set_result(None)
        self.pending = None

    async def tick(self, extra=0):
        self.advance(extra)
        return await self.paused()


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch)


class AliasServer(MockIntelliCenterServer):
    """Record subscription order and notify only the first shared-storage alias."""

    def __init__(self):
        super().__init__()
        self.subscriptions = []
        self.reads = []
        self.websockets = []
        self.add_object("air", "SENSE", "AIR", "Arbitrary name", SOURCE="70", PROBE="70", CALIB="4")
        self.add_object("water", "SENSE", "WATER", "Arbitrary name", SOURCE="71", PROBE="71")
        self.add_object("body", "BODY", "POOL", "Arbitrary name", TEMP="71", LSTTMP="71")
        self.add_object("solar", "SENSE", "SOLAR", "Arbitrary name")
        self.add_object("salt", "CHEM", "ICHLOR", "Arbitrary name", SALT="3200")
        self.add_object("chem", "CHEM", "ICHEM", "Arbitrary name", SALT="3100")
        self._handlers["RequestParamList"] = self.subscribe
        self._handlers["GetParamList"] = self.read

    async def subscribe(self, msg):
        self.subscriptions.extend(
            (e["objnam"], key) for e in msg["objectList"] for key in e["keys"]
        )
        return await self._handle_request_param_list(msg)

    async def read(self, msg):
        if all(e["objnam"] != "INCR" for e in msg["objectList"]):
            self.reads.append(msg["objectList"])
        return await self._handle_get_param_list(msg)

    async def transition(self):
        self.update_object("air", SOURCE="68", PROBE="64")
        self.update_object("water", SOURCE="69", PROBE="65")
        self.update_object("body", TEMP="67", LSTTMP="66")
        self.update_object("solar", SOURCE="81", PROBE="77")
        self.update_object("salt", SALT="3300")
        self.update_object("chem", SALT="9999")
        groups = [
            [("air", "SOURCE"), ("air", "PROBE")],
            [("water", "SOURCE"), ("water", "PROBE"), ("body", "TEMP")],
        ]
        entries = []
        for group in groups:
            objnam, key = next(pair for pair in self.subscriptions if pair in group)
            entries.append({"objnam": objnam, "params": {key: self.get_object(objnam)[key]}})
        await self.send_notification(entries)

    async def _broadcast(self, msg):
        await super()._broadcast(msg)
        for websocket in self.websockets:
            await websocket.send(orjson.dumps(msg).decode())

    async def websocket_client(self, websocket):
        self.websockets.append(websocket)
        try:
            async for packet in websocket:
                response = await self._process_message(orjson.loads(packet))
                await websocket.send(orjson.dumps(response).decode())
        finally:
            self.websockets.remove(websocket)


class OrderedModel(PoolModel):
    def __init__(self, air_first, water_first):
        super().__init__()
        self.air_first = air_first
        self.water_first = water_first

    def attributes_to_track(self):
        entries = super().attributes_to_track()
        for entry in entries:
            if entry["objnam"] == "air":
                entry["keys"].sort(key=lambda key: key != self.air_first)
        entries.sort(
            key=lambda entry: entry["objnam"] != ("body" if self.water_first == "TEMP" else "water")
        )
        if self.water_first == "SOURCE":
            for entry in entries:
                if entry["objnam"] == "water":
                    entry["keys"].sort(key=lambda key: key != "SOURCE")
        return entries


class HookController(ICModelController):
    """Exercise the same override point used by the HA controller subclass."""

    def __init__(self, *args, **kwargs):
        self.ingress = []
        super().__init__(*args, **kwargs)

    def _apply_updates(self, entries):
        self.ingress.append(entries)
        return super()._apply_updates(entries)


@asynccontextmanager
async def running(clock, *, transport="tcp", model=None, interval=60.0, server=None):
    server = server or AliasServer()
    async with server, serve(server.websocket_client, "127.0.0.1", 0) as websocket_server:
        port = server.port if transport == "tcp" else websocket_server.sockets[0].getsockname()[1]
        controller = HookController(
            "127.0.0.1",
            model or PoolModel(),
            port,
            transport=transport,
            telemetry_reconcile_interval=interval,
        )
        try:
            await controller.start()
            if interval is not None:
                await clock.paused()
            yield controller, server
        finally:
            await controller.stop()


@pytest.mark.parametrize("transport", ["tcp", "websocket"])
@pytest.mark.parametrize("air_first", ["SOURCE", "PROBE"])
@pytest.mark.parametrize("water_first", ["SOURCE", "TEMP"])
async def test_first_alias_only_recovers_via_callbacks(clock, transport, air_first, water_first):
    """Start -> first-alias-only push -> next interval -> all telemetry subscribers recover."""
    model = OrderedModel(air_first, water_first)
    server = AliasServer()
    async with running(clock, transport=transport, model=model, server=server) as (ctrl, server):
        assert clock.delay == 60
        assert server.reads == []
        changed = asyncio.Event()
        ctrl.subscribe(None, lambda *_: changed.set())
        await server.transition()
        await asyncio.wait_for(changed.wait(), 3)
        assert model["air"][air_first] == ("68" if air_first == "SOURCE" else "64")
        sibling = "PROBE" if air_first == "SOURCE" else "SOURCE"
        assert model["air"][sibling] == "70"
        if water_first == "SOURCE":
            assert model["body"]["TEMP"] == "71"
        else:
            assert model["water"]["SOURCE"] == "71"
        seen, legacy = [], []
        ctrl.ingress.clear()
        ctrl.subscribe(None, lambda _, updates: seen.append(dict(updates)))
        ctrl.set_updated_callback(lambda _, updates: legacy.append(dict(updates)))
        await clock.tick()
        expected = {
            "air": {"SOURCE": "68", "PROBE": "64"},
            "water": {"SOURCE": "69", "PROBE": "65"},
            "body": {"TEMP": "67", "LSTTMP": "66"},
            "solar": {"SOURCE": "81", "PROBE": "77"},
            "salt": {"SALT": "3300"},
        }
        for objnam, params in expected.items():
            assert {key: model[objnam][key] for key in params} == params
            assert all(ctrl.field_receipt(objnam, key)["age_seconds"] == 0 for key in params)
        assert model["air"]["CALIB"] == "4"
        assert model["chem"]["SALT"] == "3100"
        assert len(server.reads) == len(seen) == len(legacy) == 1
        assert seen == legacy
        assert len(ctrl.ingress) == 1
        assert len({entry["objnam"] for entry in ctrl.ingress[0]}) == len(ctrl.ingress[0])
        assert seen[0]["solar"] == expected["solar"]
        assert seen[0]["body"] == (
            {"TEMP": "67", "LSTTMP": "66"} if water_first == "SOURCE" else {"LSTTMP": "66"}
        )
        await clock.tick()
        assert len(seen) == 1, "unchanged telemetry must refresh receipts without a callback"
        assert ctrl.field_receipt("air", "PROBE")["age_seconds"] == 0


@pytest.mark.parametrize("ingress", ["push", "read"])
@pytest.mark.parametrize("unchanged", [False, True])
async def test_newer_ingress_wins_and_split_response_coalesces(clock, ingress, unchanged):
    """A caller observing a push/other read during recovery keeps its newer per-field observation."""
    async with running(clock) as (ctrl, server):
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(cmd, extra):
            entered.set()
            await release.wait()
            return {
                "objectList": [
                    {"objnam": "air", "params": {"SOURCE": "60", "CALIB": "999"}},
                    {"objnam": "air", "params": {"PROBE": "56"}},
                    {"objnam": "body", "params": {"TEMP": "59"}},
                    {"objnam": "solar", "params": {"SOURCE": "80"}},
                    {"objnam": "solar", "params": {"PROBE": "76"}},
                    {"objnam": "chem", "params": {"SALT": "9999"}},
                    {"objnam": "alien", "params": {"SOURCE": "42"}},
                ]
            }

        ctrl.send_cmd = AsyncMock(side_effect=delayed)
        clock.advance()
        await asyncio.wait_for(entered.wait(), 3)
        value = "70" if unchanged else "72"
        entries = [{"objnam": "air", "params": {"SOURCE": value}}]
        if ingress == "push":
            ctrl._on_notification({"command": "NotifyList", "objectList": entries})
        else:
            # Other controller reads use this same model ingress (monitor backfill).
            ctrl._apply_updates(entries)
        clock.now += 2
        seen = []
        ctrl.subscribe(None, lambda _, updates: seen.append(dict(updates)))
        release.set()
        await clock.paused()
        assert ctrl.model["air"]["SOURCE"] == value
        assert ctrl.model["air"]["PROBE"] == "56"
        assert ctrl.model["air"]["CALIB"] == "4"
        assert ctrl.model["body"]["LSTTMP"] == "71"
        assert ctrl.model["chem"]["SALT"] == "3100"
        assert "alien" not in ctrl.model
        assert seen == [
            {
                "air": {"PROBE": "56"},
                "body": {"TEMP": "59"},
                "solar": {"SOURCE": "80", "PROBE": "76"},
            }
        ]
        assert ctrl.field_receipt("air", "SOURCE")["age_seconds"] == 2
        assert not ctrl._telemetry_inflight and not ctrl._telemetry_dirty


@pytest.mark.parametrize(
    "boundary",
    [
        "stop",
        "reconnect",
        "failed_restart",
        "generation",
        "replacement",
        "connection",
        "disconnect",
    ],
)
async def test_obsolete_readback_cannot_change_model_receipts_or_listeners(clock, boundary):
    """Stop/restart or replace an object while recovery is in flight; obsolete values stay out."""
    async with running(clock) as (ctrl, server):
        entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = ctrl.send_cmd

        async def delayed(cmd, extra=None):
            if asyncio.current_task().get_name() != "intellicenter-telemetry-reconcile":
                return await original(cmd, extra)
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            return {"objectList": [{"objnam": "air", "params": {"SOURCE": "999"}}]}

        ctrl.send_cmd = delayed
        seen = []
        ctrl.subscribe(None, lambda _, updates: seen.append(dict(updates)))
        clock.advance()
        await asyncio.wait_for(entered.wait(), 3)
        if boundary in {"stop", "reconnect", "failed_restart"}:
            if boundary == "failed_restart":

                async def fail_snapshot(*args):
                    raise ICCommandError("500")

                ctrl.get_all_objects = fail_snapshot
            operation = asyncio.create_task(ctrl.stop() if boundary == "stop" else ctrl.start())
            await asyncio.wait_for(cancelled.wait(), 3)
            assert not operation.done(), "teardown must await the cancelled request"
            release.set()
            if boundary == "failed_restart":
                with pytest.raises(ICCommandError):
                    await operation
            else:
                await operation
            if boundary == "reconnect":
                await clock.paused()
        else:
            if boundary == "generation":
                ctrl._receipt_generation += 1
            elif boundary == "replacement":
                ctrl.model.remove_object("air")
                ctrl.model.add_objects(
                    [
                        {
                            "objnam": "air",
                            "params": {"OBJTYP": "SENSE", "SUBTYP": "AIR", "SOURCE": "70"},
                        }
                    ]
                )
            elif boundary == "connection":
                old_connection = ctrl._connection
                ctrl._connection = SimpleNamespace(connected=True)
            else:
                await ctrl._connection.disconnect()
            before = ctrl.field_receipt("air", "SOURCE")
            release.set()
            await clock.paused()
            assert ctrl.field_receipt("air", "SOURCE") == before
            if boundary == "connection":
                ctrl._connection = old_connection
        assert ctrl.model["air"]["SOURCE"] == "70"
        assert seen == []
        if boundary in {"stop", "failed_restart"}:
            assert ctrl._telemetry_task is None
            assert not ctrl.connected


async def test_start_stop_and_disable_own_exactly_one_worker(clock):
    """Repeated public start replaces its worker; stop awaits it; disabled callers never spawn it."""
    async with running(clock) as (ctrl, server):
        first = ctrl._telemetry_task
        await ctrl.start()
        await clock.paused()
        assert first.done()
        second = ctrl._telemetry_task
        assert second is not first and not second.done()
        await ctrl._connection.disconnect()
        await clock.tick()
        assert server.reads == []
        await ctrl.stop()
        assert second.done() and ctrl._telemetry_task is None
    async with running(clock, interval=None) as (ctrl, server):
        assert ctrl._telemetry_task is None
        assert server.reads == []


@pytest.mark.parametrize("interval", [29.9, 900.1, math.inf, -math.inf, math.nan])
def test_constructor_rejects_invalid_interval(interval):
    """A caller configuring an invalid polling interval gets an immediate ValueError."""
    with pytest.raises(ValueError, match="telemetry_reconcile_interval"):
        ICModelController("127.0.0.1", PoolModel(), telemetry_reconcile_interval=interval)


@pytest.mark.parametrize("interval", [30.0, 900.0])
async def test_inventory_rotation_respects_bound_and_rebuilds_targets(clock, interval):
    """A large installation receives every tracked target within ceil(keys/50) scheduled ticks."""
    model = PoolModel(attribute_map={"SENSE": {"SOURCE", "PROBE"}, "CHEM": {"SALT"}})
    server = AliasServer()
    for index in range(27):
        server.add_object(f"s{index:02}", "SENSE", "AIR", "Any", SOURCE="1", PROBE="2")
    for index in range(3):
        server.add_object(f"c{index:02}", "CHEM", "ICHLOR", "Any", SALT="3")
    async with running(clock, model=model, server=server, interval=interval) as (ctrl, server):
        expected = {
            (obj.objnam, key)
            for obj in model
            for key in (
                ("SOURCE", "PROBE")
                if obj.objtype == "SENSE"
                else ("SALT",)
                if obj.subtype == "ICHLOR"
                else ()
            )
        }
        ticks = math.ceil(len(expected) / 50)
        for _ in range(ticks * 2):
            before = len(server.reads)
            await clock.tick()
            assert len(server.reads) == before + 1
        for start in (0, ticks):
            seen = set()
            for query in server.reads[start : start + ticks]:
                assert len({e["objnam"] for e in query}) == len(query)
                pairs = {(e["objnam"], key) for e in query for key in e["keys"]}
                assert len(pairs) <= 50
                seen |= pairs
            assert seen == expected
        # Removing a target and changing the tracked set takes effect next tick.
        model.remove_object("s00")
        model._attribute_map["SENSE"] = {"SOURCE"}
        for _ in range(ticks):
            await clock.tick()
        assert all(
            e["objnam"] != "s00" and "PROBE" not in e["keys"]
            for query in server.reads[-ticks:]
            for e in query
        )


@pytest.mark.parametrize("change", ["remove_before_cursor", "remove_cursor", "add_before_cursor"])
async def test_mid_rotation_inventory_change_preserves_progress(clock, change):
    """A caller changes the live inventory between ticks without starving surviving targets."""
    model = PoolModel(attribute_map={"SENSE": {"SOURCE", "PROBE"}, "CHEM": {"SALT"}})
    server = AliasServer()
    server._objects.clear()
    for index in range(26):
        server.add_object(f"s{index:02}", "SENSE", "AIR", "Any", SOURCE="0", PROBE="0")
    for index in range(8):
        server.add_object(f"c{index:02}", "CHEM", "ICHLOR", "Any", SALT="0")
    async with running(clock, model=model, server=server) as (ctrl, server):
        for index in range(26):
            server.update_object(f"s{index:02}", SOURCE="1", PROBE="1")
        for index in range(8):
            server.update_object(f"c{index:02}", SALT="1")
        await clock.tick()
        assert [entry["objnam"] for entry in server.reads[0]] == [
            f"s{index:02}" for index in range(25)
        ]
        if change == "add_before_cursor":
            server.add_object("r99", "SENSE", "AIR", "Added", SOURCE="1", PROBE="1")
            model.add_object("r99", {"OBJTYP": "SENSE", "SUBTYP": "AIR", "SOURCE": "0"})
        else:
            removed = "s00" if change == "remove_before_cursor" else "s24"
            model.remove_object(removed)
            server._objects.pop(removed)
        await clock.tick()
        assert model["s25"]["SOURCE"] == model["s25"]["PROBE"] == "1"
        assert [entry["objnam"] for entry in server.reads[1]] == [
            "s25",
            *[f"c{index:02}" for index in range(8)],
        ]
        assert all(model[f"c{index:02}"]["SALT"] == "1" for index in range(8))
        await clock.tick()
        if change == "add_before_cursor":
            assert model["r99"]["SOURCE"] == model["r99"]["PROBE"] == "1"
        assert len(server.reads) == 3
        for query in server.reads:
            assert sum(len(entry["keys"]) for entry in query) <= 50
            assert len({entry["objnam"] for entry in query}) == len(query)


async def test_completed_rotation_insertion_recovers_existing_alias(clock):
    """A sensor added after a completed read cannot delay recovery of an existing starved alias."""
    server = AliasServer()
    server._objects.clear()
    server.add_object("s00", "SENSE", "AIR", "Existing", SOURCE="0", PROBE="0")
    async with running(clock, server=server) as (ctrl, server):
        await clock.tick()
        assert [entry["objnam"] for entry in server.reads[0]] == ["s00"]
        server.update_object("s00", SOURCE="1", PROBE="1")
        pushed = asyncio.Event()
        ctrl.subscribe("s00", lambda *_: pushed.set())
        await server.send_notification([{"objnam": "s00", "params": {"SOURCE": "1"}}])
        await asyncio.wait_for(pushed.wait(), 3)
        assert ctrl.model["s00"]["SOURCE"] == "1" and ctrl.model["s00"]["PROBE"] == "0"
        server.add_object("s01", "SENSE", "AIR", "Added", SOURCE="1", PROBE="1")
        ctrl.model.add_object(
            "s01", {"OBJTYP": "SENSE", "SUBTYP": "AIR", "SOURCE": "0", "PROBE": "0"}
        )
        seen = []
        ctrl.subscribe(None, lambda _, updates: seen.append(dict(updates)))
        await clock.tick()
        assert ctrl.model["s00"]["PROBE"] == "1"
        assert [entry["objnam"] for entry in server.reads[1]] == ["s00", "s01"]
        assert sum(len(entry["keys"]) for entry in server.reads[1]) == 4
        assert len(server.reads) == 2
        assert seen == [{"s00": {"PROBE": "1"}, "s01": {"SOURCE": "1", "PROBE": "1"}}]


async def test_unexpected_model_error_backs_off_and_recovers(clock, monkeypatch, caplog):
    """A transient exception in a consumer's model ingress cannot permanently stop scheduled reads."""
    async with running(clock) as (ctrl, server):
        caplog.set_level("DEBUG", logger="pyintellicenter.controller")
        worker = ctrl._telemetry_task
        process_updates = ctrl.model.process_updates
        entered = asyncio.Event()
        attempts = 0
        send_cmd = ctrl.send_cmd
        first_request = True

        async def timeout_then_read(*args, **kwargs):
            nonlocal first_request
            if first_request:
                first_request = False
                raise ICTimeoutError("outage", delivery_uncertain=True)
            return await send_cmd(*args, **kwargs)

        def transient_failure(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            entered.set()
            if attempts <= 2:
                raise RuntimeError("temporary model ingress failure")
            return process_updates(*args, **kwargs)

        monkeypatch.setattr(ctrl.model, "process_updates", transient_failure)
        monkeypatch.setattr(ctrl, "send_cmd", timeout_then_read)
        server.update_object("air", SOURCE="68", PROBE="64")
        seen = []
        ctrl.subscribe("air", lambda _, updates: seen.append(dict(updates)))
        assert await clock.tick() == 120
        for delay in (240, 480):
            entered.clear()
            clock.advance()
            await asyncio.wait_for(entered.wait(), 3)
            assert not worker.done(), (
                "an unexpected ingress exception must not terminate the worker"
            )
            assert await clock.paused() == delay
            assert ctrl.model["air"]["SOURCE"] == "70"
            assert seen == []
        assert await clock.tick() == 60
        assert ctrl._telemetry_task is worker
        assert len(server.reads) == attempts == 3
        assert seen == [{"air": {"SOURCE": "68", "PROBE": "64"}}]
        errors = [record for record in caplog.records if record.exc_info]
        assert len(errors) == 1 and errors[0].exc_info[0] is RuntimeError
        assert sum("Telemetry reconciliation recovered" in r.message for r in caplog.records) == 1
        attempts = 0
        assert await clock.tick() == 120
        errors = [record for record in caplog.records if record.exc_info]
        assert len(errors) == 2 and errors[1].exc_info[0] is RuntimeError


async def test_failure_backoff_cap_reset_queue_exemption_and_missed_ticks(clock, caplog):
    """Scheduled recovery backs off an outage, ignores queue-only timeouts, then resumes cadence."""
    async with running(clock) as (ctrl, server):
        caplog.set_level("DEBUG", logger="pyintellicenter.controller")
        outcomes = iter(
            [
                ICTimeoutError("queued"),
                *[ICTimeoutError("sent", delivery_uncertain=True) for _ in range(6)],
                {"objectList": []},
                {"objectList": []},
            ]
        )

        async def slow_request(*args, **kwargs):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                clock.now += 10
                raise outcome
            return outcome

        ctrl.send_cmd = AsyncMock(side_effect=slow_request)
        delays = [await clock.tick() for _ in range(8)]
        assert delays == [60, 120, 240, 480, 900, 900, 900, 60]
        assert (
            sum(
                "Telemetry reconciliation failed" in r.message and r.levelname == "WARNING"
                for r in caplog.records
            )
            == 1
        )
        assert sum("Telemetry reconciliation recovered" in r.message for r in caplog.records) == 1
        await clock.tick(extra=125)
        assert ctrl.send_cmd.await_count == 9
        assert clock.delay == 55, "missed ticks are skipped without a burst or schedule drift"
