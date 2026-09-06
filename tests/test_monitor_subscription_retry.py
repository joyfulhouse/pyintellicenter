"""Regression tests for issue #91: runtime monitor subscriptions are retried.

A NotifyList that introduces a new object adds it to the model and queues one
RequestParamList so the panel starts pushing its tracked attributes. The
object never re-appears as "added", so if that single request fails
transiently nothing would ever subscribe it until the next reconnect. The
controller now keeps a pending set drained by one backoff worker; these tests
pin that behaviour down.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from pyintellicenter import (
    ICCommandError,
    ICConnectionError,
    ICConnectionHandler,
    ICModelController,
    PoolModel,
)
from pyintellicenter import controller as controller_module
from pyintellicenter.exceptions import ICTimeoutError
from tests.mock_server import MockIntelliCenterServer

CHM02 = {
    "objnam": "CHM02",
    "params": {"OBJTYP": "CHEM", "SUBTYP": "ICHEM", "SNAME": "IntelliChem 2"},
}
CHM03 = {
    "objnam": "CHM03",
    "params": {"OBJTYP": "CHEM", "SUBTYP": "ICHEM", "SNAME": "IntelliChem 3"},
}
ACK = {"response": "200", "objectList": []}


def notify(controller: ICModelController, *entries: dict) -> None:
    """Deliver a NotifyList introducing the given objects."""
    controller._on_notification({"command": "NotifyList", "objectList": list(entries)})


async def drain(controller: ICModelController) -> None:
    """Wait for whatever monitor task(s) the last notification scheduled."""
    await asyncio.gather(*controller._monitor_tasks)


def targeted(send_cmd: AsyncMock) -> list[list[str]]:
    """The objnams covered by each RequestParamList the mock saw, in order."""
    return [
        [item["objnam"] for item in call.args[1]["objectList"]]
        for call in send_cmd.await_args_list
        if call.args[0] == "RequestParamList"
    ]


@pytest.fixture
def model() -> PoolModel:
    return PoolModel()


@pytest.fixture
def controller(model: PoolModel) -> ICModelController:
    return ICModelController("192.168.1.100", model, 6681)


@pytest.fixture
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry immediately so the tests do not wait out real backoff."""
    monkeypatch.setattr(controller_module, "MONITOR_RETRY_BASE_DELAY", 0, raising=False)


@pytest.fixture
def small_attribute_map(monkeypatch: pytest.MonkeyPatch, model: PoolModel) -> None:
    """Track few CHEM keys so two objects fit in one bounded RequestParamList.

    The real CHEM set is large enough that two objects split into two batches
    (MAX_ATTRIBUTES_PER_QUERY), which is the existing batching at work, not
    the merge semantics under test here.
    """
    monkeypatch.setattr(model, "_attribute_map", {"CHEM": {"PHVAL", "ORPVAL"}})


class TestMonitorSubscriptionRetry:
    """Pending-set + single drain worker semantics (issue #91)."""

    @pytest.mark.usefixtures("no_backoff")
    async def test_timeout_then_success_retries_without_reconnect(self, controller, model):
        """(a) One timeout, then success: exactly two requests, nothing left pending.

        This is the issue's reproduction. No reconnect and no further
        notification for the object is needed, and the acknowledged response
        still reaches the model and the updated callback as before.
        """
        controller.send_cmd = AsyncMock(
            side_effect=[
                ICTimeoutError("no reply"),
                {
                    "response": "200",
                    "objectList": [{"objnam": "CHM02", "params": {"PHVAL": "7.4"}}],
                },
            ]
        )
        seen: list[dict] = []
        controller.set_updated_callback(lambda _ctrl, updates: seen.append(dict(updates)))

        notify(controller, CHM02)
        await drain(controller)

        assert targeted(controller.send_cmd) == [["CHM02"], ["CHM02"]]
        assert controller._pending_monitor == set()
        assert model["CHM02"]["PHVAL"] == "7.4"
        assert any((updates.get("CHM02") or {}).get("PHVAL") == "7.4" for updates in seen)

        # Re-delivering the introduction (the object is already in the model)
        # must not queue anything: the retry, not a new notification, fixed it.
        notify(controller, CHM02)
        assert controller._pending_monitor == set()
        assert controller.send_cmd.await_count == 2

    @pytest.mark.usefixtures("no_backoff")
    async def test_malformed_response_then_success(self, controller):
        """(b) Missing and non-list objectList replies are retried until a usable one."""
        controller.send_cmd = AsyncMock(
            side_effect=[{"response": "200"}, {"response": "200", "objectList": "nope"}, ACK]
        )

        notify(controller, CHM02)
        await drain(controller)

        assert targeted(controller.send_cmd) == [["CHM02"]] * 3
        assert controller._pending_monitor == set()

    @pytest.mark.usefixtures("no_backoff", "small_attribute_map")
    async def test_simultaneous_additions_share_one_request(self, controller):
        """(c) Two additions delivered before yielding go out as ONE RequestParamList."""
        controller.send_cmd = AsyncMock(return_value=ACK)

        notify(controller, CHM02)
        notify(controller, CHM03)
        assert len(controller._monitor_tasks) == 1, "a second worker was spawned"
        await drain(controller)

        assert targeted(controller.send_cmd) == [["CHM02", "CHM03"]]
        assert controller._pending_monitor == set()

    async def test_command_error_is_logged_and_not_retried(self, controller, caplog):
        """(d) A panel rejection is permanent: one request, WARNING with the code, dropped."""
        controller.send_cmd = AsyncMock(side_effect=ICCommandError("400"))
        real_sleep = asyncio.sleep
        sleeps: list[float] = []

        async def recording_sleep(delay, *args, **kwargs):
            sleeps.append(delay)
            await real_sleep(0)

        with (
            patch("asyncio.sleep", new=recording_sleep),
            caplog.at_level(logging.WARNING, logger="pyintellicenter.controller"),
        ):
            notify(controller, CHM02)
            await drain(controller)

        assert controller.send_cmd.await_count == 1
        assert controller._pending_monitor == set()
        assert sleeps == [], "a rejected command must not enter backoff"
        assert any(
            record.levelno == logging.WARNING and "400" in record.getMessage()
            for record in caplog.records
        )

    @pytest.mark.usefixtures("small_attribute_map")
    async def test_extended_outage_backoff_is_exponential_and_capped(self, controller):
        """(e) N timeouts: sleeps double from 1s and cap at 60s; one worker, one in flight.

        An addition that arrives mid-outage merges into the same worker's next
        attempt instead of spawning a second worker.
        """
        real_sleep = asyncio.sleep
        sleeps: list[float] = []

        async def recording_sleep(delay, *args, **kwargs):
            sleeps.append(delay)
            await real_sleep(0)

        outcomes: list = [ICTimeoutError("no reply")] * 8 + [ACK]
        calls = 0
        in_flight = 0
        max_in_flight = 0
        sending_tasks: set = set()

        async def fake_send_cmd(cmd, extra=None):
            nonlocal calls, in_flight, max_in_flight
            calls += 1
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            sending_tasks.add(asyncio.current_task())
            try:
                if calls == 3:
                    # New equipment announced while a request is in flight.
                    notify(controller, CHM03)
                await real_sleep(0)
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            finally:
                in_flight -= 1

        controller.send_cmd = AsyncMock(side_effect=fake_send_cmd)
        with patch("asyncio.sleep", new=recording_sleep):
            notify(controller, CHM02)
            await drain(controller)

        assert sleeps == [1, 2, 4, 8, 16, 32, 60, 60]
        assert controller.send_cmd.await_count == 9
        assert max_in_flight == 1
        assert len(sending_tasks) == 1
        assert controller._pending_monitor == set()
        covered = targeted(controller.send_cmd)
        assert covered[:3] == [["CHM02"]] * 3
        assert covered[3:] == [["CHM02", "CHM03"]] * 6

    async def test_stop_during_backoff_cancels_and_awaits_worker(self, controller, monkeypatch):
        """(f) stop() while the worker is parked in backoff cancels it cleanly."""
        monkeypatch.setattr(controller_module, "MONITOR_RETRY_BASE_DELAY", 3600, raising=False)
        controller.send_cmd = AsyncMock(side_effect=ICTimeoutError("no reply"))

        notify(controller, CHM02)
        worker = next(iter(controller._monitor_tasks))
        # Let the first attempt fail and the worker enter its (long) sleep.
        for _ in range(10):
            await asyncio.sleep(0)
        assert controller.send_cmd.await_count == 1
        assert not worker.done()

        await controller.stop()

        assert worker.cancelled()
        assert controller._monitor_tasks == set()
        assert controller.send_cmd.await_count == 1

    async def test_reconnect_start_supersedes_pending_retry(self, monkeypatch):
        """(g) Connection replacement mid-retry: start() clears the pending set and
        the full resubscribe it builds covers the object."""
        monkeypatch.setattr(controller_module, "MONITOR_RETRY_BASE_DELAY", 3600, raising=False)
        async with MockIntelliCenterServer() as server:
            server.set_system_info("Retry Pool", "2.0.0")
            server.add_object("POOL1", "BODY", "POOL", "Pool", STATUS="OFF")
            model = PoolModel()
            controller = ICModelController(server.host, model, server.port)
            handler = ICConnectionHandler(
                controller, time_between_reconnects=0, disconnect_debounce_time=0
            )
            started = asyncio.Event()
            reconnected = asyncio.Event()
            handler.on_started = lambda _ctrl: started.set()
            handler.on_reconnected = lambda _ctrl: reconnected.set()

            await handler.start()
            try:
                await asyncio.wait_for(started.wait(), timeout=5.0)

                # The first RequestParamList after this point times out; all
                # other traffic (including the reconnect's resubscribe) is real.
                real_send_cmd = controller.send_cmd
                request_lists: list[list[str]] = []
                fail_next = True

                async def flaky_send_cmd(cmd, extra=None):
                    nonlocal fail_next
                    if cmd == "RequestParamList":
                        request_lists.append([item["objnam"] for item in extra["objectList"]])
                        if fail_next:
                            fail_next = False
                            raise ICTimeoutError("no reply")
                    return await real_send_cmd(cmd, extra)

                controller.send_cmd = flaky_send_cmd

                # Equipment installed while connected: the panel lists it and
                # announces it.
                server.add_object("CHM02", "CHEM", "ICHEM", "IntelliChem 2")
                await server.send_notification([CHM02])
                for _ in range(500):
                    if request_lists:
                        break
                    await asyncio.sleep(0.01)
                assert request_lists == [["CHM02"]]
                worker = next(iter(controller._monitor_tasks), None)
                assert worker is not None and not worker.done(), "worker gave up"
                assert controller._pending_monitor == {"CHM02"}

                # The link drops; the handler reconnects, which runs start().
                handler._on_disconnect(controller, Exception("dropped"))
                await asyncio.wait_for(reconnected.wait(), timeout=5.0)

                assert worker.cancelled()
                assert controller._pending_monitor == set()
                assert any("CHM02" in batch for batch in request_lists[1:])
            finally:
                await handler.astop()

    @pytest.mark.usefixtures("no_backoff", "small_attribute_map")
    async def test_object_removed_while_pending_is_dropped(self, controller, model):
        """(h) An object pruned from the model while pending is left out of the retry."""
        calls = 0

        async def fake_send_cmd(cmd, extra=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                # First attempt fails; before the retry the panel forgets CHM02.
                model.remove_object("CHM02")
                raise ICTimeoutError("no reply")
            return ACK

        controller.send_cmd = AsyncMock(side_effect=fake_send_cmd)

        notify(controller, CHM02, CHM03)
        await drain(controller)

        assert targeted(controller.send_cmd) == [["CHM02", "CHM03"], ["CHM03"]]
        assert controller._pending_monitor == set()

    @pytest.mark.usefixtures("no_backoff")
    async def test_connection_error_ends_worker_without_retry(self, controller):
        """A dead link is the reconnect path's job: the worker stops, nothing is retried."""
        controller.send_cmd = AsyncMock(side_effect=ICConnectionError("gone"))

        notify(controller, CHM02)
        await drain(controller)

        assert controller.send_cmd.await_count == 1
        # Left in place for the reconnect's start() to clear and rebuild.
        assert controller._pending_monitor == {"CHM02"}
