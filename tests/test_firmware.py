"""Firmware tests: synthetic lifecycle scripts are not hardware validation."""

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pyintellicenter import (
    FirmwareUpdatePhase as Phase,
)
from pyintellicenter import (
    ICBaseController,
    ICCommandError,
    ICConnectionError,
    ICConnectionHandler,
    ICError,
    ICModelController,
    ICResponseError,
    ICSystemInfo,
    ICTimeoutError,
    PoolModel,
    firmware,
)
from pyintellicenter.attributes.system import SYSTEM_ATTRIBUTES

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/firmware/synthetic_contract.json").read_text()
)


class ScriptedConnection:
    """Fake transport; no network access or real device commands."""

    def __init__(self) -> None:
        self.connected = True
        self.observers: list[Any] = []
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.sequence = 0
        self.error: BaseException | None = None
        self.response: dict[str, Any] = {"response": "200"}
        self.gate: asyncio.Event | None = None
        self.started = asyncio.Event()
        self.during_send: Any = None
        self.before_dispatch: Any = None

    def add_notification_observer(self, callback: Any) -> Any:
        self.observers.append(callback)

        def remove() -> None:
            self.observers.remove(callback)

        return remove

    def emit(self, params: Any, objnam: str = "_5451") -> None:
        self.sequence += 1
        for observer in tuple(self.observers):
            observer(self.sequence, {"objectList": [{"objnam": objnam, "params": params}]})

    async def send_request(self, command: str, **kwargs: Any) -> dict[str, Any]:
        before = kwargs.pop("_before_write_callback", None)
        if self.before_dispatch:
            self.before_dispatch()
        if before:
            before(self.sequence, asyncio.get_running_loop().time())
        self.requests.append((command, kwargs))
        self.started.set()
        if self.during_send:
            self.during_send()
        if self.gate:
            await self.gate.wait()
        if self.error:
            raise self.error
        return self.response

    async def disconnect(self) -> None:
        self.connected = False


def make_controller(model: bool = False) -> tuple[ICBaseController, ScriptedConnection]:
    controller = (
        ICModelController("unused.invalid", PoolModel())
        if model
        else ICBaseController("unused.invalid")
    )
    controller._system_info = ICSystemInfo(
        "_5451", {"VER": "fixture-source", "PROPNAME": "Test", "MODE": "ENGLISH", "SNAME": "Test"}
    )
    connection = ScriptedConnection()
    controller._connection = connection  # type: ignore[assignment]
    controller._firmware.attach(connection)  # type: ignore[arg-type]
    connection.emit(FIXTURE["initial"])
    return controller, connection


@pytest.fixture
def supported(monkeypatch: pytest.MonkeyPatch) -> tuple[ICBaseController, ScriptedConnection]:
    contract = firmware._FirmwareSupportContract(
        source_version=FIXTURE["source_version"],
        target_version=FIXTURE["target_version"],
        required_params=tuple(tuple(item) for item in FIXTURE["required_params"]),
        evidence=FIXTURE["evidence"],
    )
    monkeypatch.setattr(firmware, "_VALIDATED_INSTALL_CONTRACTS", (contract,))
    return make_controller()


async def install(controller: ICBaseController, **kwargs: Any) -> Any:
    return await controller.request_firmware_install(FIXTURE["target_version"], **kwargs)


async def test_no_hardware_contract_or_force_switch() -> None:
    controller, connection = make_controller()
    for version in ("1.064", "3.008", "fixture-source"):
        connection.emit({"VER": version, "UPDATE": "1", "IN": "YES", "PROGRESS": "100"})
        state = controller.firmware_update
        assert state.available is True
        assert not state.capability.install_supported
        assert not state.capability.eligible
        assert not state.capability.decline_supported
        assert not state.capability.cancel_supported
        with pytest.raises(ICError, match="No validated"):
            await install(controller)
    assert not connection.requests


@pytest.mark.parametrize(
    "raw, available",
    [
        ("1", True),
        (1, True),
        ("0", False),
        (0, False),
        (True, None),
        ("UPDATE", None),
        ("unknown:target", None),
        ({"new": 1}, None),
        (None, None),
    ],
)
async def test_availability_preserves_unknown_values(raw: Any, available: bool | None) -> None:
    controller, connection = make_controller()
    connection.emit({"UPDATE": raw, "IN": {"new": [1]}, "AUTO": "future"})
    state = controller.firmware_update
    assert state.available is available
    assert state.raw["UPDATE"] == raw
    state.raw["IN"]["new"].append(2)
    assert controller.firmware_update.raw["IN"] == {"new": [1]}


async def test_fdr_and_other_systems_are_excluded() -> None:
    controller, connection = make_controller()
    original = controller.firmware_update
    connection.emit({"EVENTSTATUS": "running", "EVENTID": "1", "PROGRESS": "100"}, "_FDR")
    connection.emit({"PROGRESS": "100"}, "other-system")
    assert controller.firmware_update == original
    assert "EVENTSTATUS" not in SYSTEM_ATTRIBUTES
    assert {"VER", "UPDATE", "IN", "PROGRESS", "AUTO"} <= SYSTEM_ATTRIBUTES


async def test_ack_is_not_completion_and_exact_install_encoding(supported: Any) -> None:
    controller, connection = supported
    state = await install(controller)
    assert state.phase == Phase.ACKNOWLEDGED
    assert state.acknowledged
    assert state.verified_version is None
    assert connection.requests == [
        ("SetParamList", {"objectList": [{"objnam": "_5451", "params": {"IN": "YES"}}]})
    ]
    with pytest.raises(ICError, match="already requested"):
        await install(controller)
    await controller.stop()


async def test_duplicate_concurrent_request(supported: Any) -> None:
    controller, connection = supported
    connection.gate = asyncio.Event()
    task = asyncio.create_task(install(controller))
    await connection.started.wait()
    assert controller.firmware_update.phase == Phase.REQUESTED
    with pytest.raises(ICError, match="already requested"):
        await install(controller)
    connection.gate.set()
    await task
    assert len(connection.requests) == 1
    await controller.stop()


async def test_rejection_propagates_and_remains_failed(supported: Any) -> None:
    controller, connection = supported
    connection.error = ICResponseError("403")
    with pytest.raises(ICCommandError) as raised:
        await install(controller)
    assert raised.value.error_code == "403"
    assert controller.firmware_update.phase == Phase.FAILED
    connection.emit({"PROGRESS": "100", "VER": FIXTURE["target_version"]})
    controller._on_disconnect(None)
    assert controller.firmware_update.phase == Phase.FAILED
    with pytest.raises(ICError):
        await controller.verify_firmware_update()
    with pytest.raises(ICError, match="already requested"):
        await install(controller)
    assert len(connection.requests) == 1


@pytest.mark.parametrize(
    "error",
    [
        ICTimeoutError("timeout", delivery_uncertain=True),
        ICConnectionError("lost"),
        OSError("lost"),
    ],
)
async def test_request_uncertainty_never_retries(supported: Any, error: BaseException) -> None:
    controller, connection = supported
    connection.error = error
    with pytest.raises(type(error)):
        await install(controller)
    assert controller.firmware_update.phase == Phase.UNKNOWN
    assert controller.firmware_update.reason == "request_outcome_uncertain"
    with pytest.raises(ICError, match="already requested"):
        await install(controller)
    assert len(connection.requests) == 1


@pytest.mark.parametrize("response", [{}, {"response": "200?"}])
async def test_malformed_acknowledgement_is_uncertain(supported: Any, response: Any) -> None:
    controller, connection = supported
    connection.response = response
    with pytest.raises(ICResponseError):
        await install(controller)
    assert controller.firmware_update.phase == Phase.UNKNOWN
    assert not controller.firmware_update.acknowledged


@pytest.mark.parametrize(
    "progress, phase",
    [
        (None, Phase.ACKNOWLEDGED),
        ("", Phase.ACKNOWLEDGED),
        ("PROGRESS", Phase.ACKNOWLEDGED),
        ({"percent": 100}, Phase.ACKNOWLEDGED),
        (True, Phase.ACKNOWLEDGED),
        ("100", Phase.PROGRESS_OBSERVED),
        ("future:stage", Phase.PROGRESS_OBSERVED),
        (-5, Phase.PROGRESS_OBSERVED),
        (101, Phase.PROGRESS_OBSERVED),
    ],
)
async def test_progress_is_raw_receipt_never_terminal(
    supported: Any, progress: Any, phase: Phase
) -> None:
    controller, connection = supported
    await install(controller)
    connection.emit({"PROGRESS": progress})
    state = controller.firmware_update
    assert state.raw["PROGRESS"] == progress
    assert state.phase == phase
    assert state.verified_version is None
    await controller.stop()


async def test_progress_received_before_ack_is_retained(supported: Any) -> None:
    controller, connection = supported
    connection.during_send = lambda: connection.emit({"PROGRESS": "stage:future"})
    assert (await install(controller)).phase == Phase.PROGRESS_OBSERVED
    await controller.stop()


async def test_pre_request_progress_cannot_become_current_progress(supported: Any) -> None:
    controller, connection = supported
    connection.emit({"PROGRESS": "100"})
    await install(controller)
    connection.emit({"AUTO": "future"})
    assert controller.firmware_update.phase == Phase.ACKNOWLEDGED
    await controller.stop()


async def test_reconnect_deadline_is_unknown_and_blocks_replay(supported: Any) -> None:
    controller, connection = supported
    await install(controller, verification_timeout=0.01)
    connection.connected = False
    controller._on_disconnect(None)
    assert controller.firmware_update.phase == Phase.RECONNECTING
    await asyncio.sleep(0.02)
    assert controller.firmware_update.phase == Phase.UNKNOWN
    assert controller.firmware_update.reason == "verification_timeout"
    with pytest.raises(ICError, match="already requested"):
        await install(controller)


async def test_reboot_reconnect_stale_notifications_and_fresh_verification(supported: Any) -> None:
    controller, old = supported
    stale_observer = old.observers[0]
    await install(controller)
    old.connected = False
    controller._on_disconnect(None)
    replacement = ScriptedConnection()
    controller._connection = replacement
    controller._firmware.attach(replacement)
    replacement.emit({"VER": "fixture-source"})
    stale_observer(
        999,
        {
            "objectList": [
                {"objnam": "_5451", "params": {"VER": FIXTURE["target_version"], "PROGRESS": "100"}}
            ]
        },
    )
    assert controller.firmware_update.installed_version == "fixture-source"
    assert "PROGRESS" not in controller.firmware_update.raw
    replacement.emit({"VER": FIXTURE["target_version"], "PROGRESS": "100"})
    assert controller.firmware_update.phase == Phase.RECONNECTING
    assert controller.firmware_update.verified_version is None
    replacement.response = {
        "response": "200",
        "objectList": [{"objnam": "_5451", "params": {"VER": FIXTURE["target_version"]}}],
    }
    state = await controller.verify_firmware_update()
    assert state.phase == Phase.VERIFIED
    assert state.verified_version == FIXTURE["target_version"]
    assert not controller._firmware._timer
    assert replacement.requests == [
        ("GetParamList", {"objectList": [{"objnam": "_5451", "keys": ["VER"]}]})
    ]
    assert len(old.requests) == 1
    await controller.stop()


@pytest.mark.parametrize("version", ["fixture-source", "unexpected-version"])
async def test_fresh_version_must_equal_target(supported: Any, version: str) -> None:
    controller, connection = supported
    await install(controller)
    connection.response = {
        "response": "200",
        "objectList": [{"objnam": "_5451", "params": {"VER": version}}],
    }
    state = await controller.verify_firmware_update()
    assert state.phase == Phase.UNKNOWN
    assert state.reason == "target_version_not_observed"
    assert state.verified_version is None
    await controller.stop()


@pytest.mark.parametrize(
    "entries",
    [
        None,
        [],
        {},
        [{"objnam": "_5451", "params": {}}],
        [{"objnam": "_5451", "params": {"VER": "VER"}}],
        [{"objnam": "_5451", "params": {"VER": 123}}],
        [{"objnam": "_5451", "params": {"VER": "fixture-target"}}] * 2,
    ],
)
async def test_missing_or_malformed_verification(supported: Any, entries: Any) -> None:
    controller, connection = supported
    await install(controller)
    connection.response = {"response": "200", "objectList": entries}
    with pytest.raises(ICResponseError):
        await controller.verify_firmware_update()
    assert controller.firmware_update.phase == Phase.UNKNOWN
    await controller.stop()


async def test_verification_response_from_replaced_connection_is_rejected(supported: Any) -> None:
    controller, connection = supported
    await install(controller)
    connection.gate = asyncio.Event()
    connection.started.clear()
    task = asyncio.create_task(controller.verify_firmware_update())
    await connection.started.wait()
    replacement = ScriptedConnection()
    controller._connection = replacement
    connection.gate.set()
    with pytest.raises(ICConnectionError):
        await task
    assert controller.firmware_update.verified_version is None
    await controller.stop()


async def test_cancel_request_is_uncertain_without_panel_cancel(supported: Any) -> None:
    controller, connection = supported
    connection.gate = asyncio.Event()
    task = asyncio.create_task(install(controller))
    await connection.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert controller.firmware_update.phase == Phase.UNKNOWN
    with pytest.raises(ICError, match="already requested"):
        await install(controller)
    assert len(connection.requests) == 1


async def test_watcher_cancellation_only_removes_listener(supported: Any) -> None:
    controller, connection = supported
    await install(controller)
    watcher = controller.watch_firmware_update()
    assert (await anext(watcher)).phase == Phase.ACKNOWLEDGED
    pending = asyncio.create_task(anext(watcher))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not controller._firmware._watchers
    assert controller.firmware_update.phase == Phase.ACKNOWLEDGED
    with pytest.raises(ICError, match="already requested"):
        await install(controller)
    assert len(connection.requests) == 1
    await controller.stop()


async def test_watcher_is_bounded_and_independent() -> None:
    controller, connection = make_controller()
    first = controller.watch_firmware_update()
    second = controller.watch_firmware_update()
    await anext(first)
    await anext(second)
    for i in range(200):
        connection.emit({"PROGRESS": str(i)})
    assert (await anext(first)).raw["PROGRESS"] == "199"
    await first.aclose()
    assert len(controller._firmware._watchers) == 1
    assert (await anext(second)).raw["PROGRESS"] == "199"
    await second.aclose()
    assert not controller._firmware._watchers
    assert not connection.requests


async def test_eligibility_and_exact_source_target_required(supported: Any) -> None:
    controller, connection = supported
    with pytest.raises(ICError, match="No validated"):
        await controller.request_firmware_install("other-target")
    connection.emit({"IN": "future-state"})
    assert controller.firmware_update.capability.install_supported
    assert not controller.firmware_update.capability.eligible
    with pytest.raises(ICError, match="eligibility"):
        await install(controller)
    connection.emit({"VER": "unvalidated-version"})
    assert not controller.firmware_update.capability.install_supported
    assert not connection.requests


async def test_queued_request_cannot_cross_reconnect(supported: Any) -> None:
    controller, old = supported
    async with controller._mutation_lifecycle():
        task = asyncio.create_task(install(controller))
        await asyncio.sleep(0)
        replacement = ScriptedConnection()
        controller._connection = replacement
    with pytest.raises(ICConnectionError):
        await task
    assert not old.requests
    assert not replacement.requests
    assert controller.firmware_update.reason == "request_not_sent"


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
async def test_invalid_deadline_never_admits_or_writes(supported: Any, value: float) -> None:
    controller, connection = supported
    with pytest.raises(ValueError):
        await install(controller, verification_timeout=value)
    assert not controller._firmware.admitted
    assert not connection.requests


async def test_model_start_and_reconnect_only_read_and_subscribe() -> None:
    from tests.mock_server import MockIntelliCenterServer

    async with MockIntelliCenterServer() as server:
        server.add_object(
            "_5451",
            "SYSTEM",
            "OCP",
            "Test System",
            VER="1.0.0",
            UPDATE="1",
            IN="IN",
            PROGRESS="PROGRESS",
            AUTO="AUTO",
        )
        original_get = server._handlers["GetParamList"]

        async def get_params(message: Any) -> Any:
            response = await original_get(message)
            if "OBJTYP=SYSTEM" in message.get("condition", ""):
                response["objectList"][0]["objnam"] = "_5451"
            return response

        server._handlers["GetParamList"] = get_params
        controller = ICModelController(server.host, PoolModel(), port=server.port)
        handler = ICConnectionHandler(
            controller, time_between_reconnects=0, disconnect_debounce_time=0
        )
        reconnected = asyncio.Event()
        handler.on_reconnected = lambda _: reconnected.set()
        try:
            with patch.object(
                server, "_process_message", wraps=server._process_message
            ) as requests:
                await handler.start()
                assert (
                    controller.firmware_update.installed_version
                    == controller.system_info.sw_version
                )
                assert controller.firmware_update.available is True
                assert controller.firmware_update.raw["PROGRESS"] == "PROGRESS"
                assert not controller.firmware_update.capability.install_supported
                server._clients[0].close()
                async with asyncio.timeout(5):
                    await reconnected.wait()
                subscriptions = []
                for call in requests.await_args_list:
                    message = call.args[0]
                    assert message["command"].casefold() in ("getparamlist", "requestparamlist")
                    if message["command"] == "RequestParamList":
                        subscriptions.extend(
                            item for item in message["objectList"] if item["objnam"] == "_5451"
                        )
                assert len(subscriptions) == 2
                assert all(
                    set(firmware.FIRMWARE_KEYS) <= set(item["keys"]) for item in subscriptions
                )
                assert controller.firmware_update.available is True
        finally:
            await handler.astop()


async def test_newer_notification_wins_over_pending_snapshot() -> None:
    controller, connection = make_controller()
    revision = controller._firmware.revision
    connection.emit({"PROGRESS": "newer-stage", "UPDATE": "future:newer"})
    controller._firmware.observe_entries(
        [
            {
                "objnam": "_5451",
                "params": {"PROGRESS": "older-stage", "UPDATE": "0", "AUTO": "new-setting"},
            }
        ],
        snapshot_revision=revision,
    )
    assert controller.firmware_update.raw["PROGRESS"] == "newer-stage"
    assert controller.firmware_update.raw["UPDATE"] == "future:newer"
    assert controller.firmware_update.raw["AUTO"] == "new-setting"


@pytest.mark.parametrize("terminal", ["rejected", "uncertain", "expired"])
async def test_reconnect_preserves_failed_and_unknown_outcomes(
    supported: Any, terminal: str
) -> None:
    controller, connection = supported
    if terminal == "rejected":
        connection.error = ICResponseError("403")
        with pytest.raises(ICCommandError):
            await install(controller)
    elif terminal == "uncertain":
        connection.error = ICTimeoutError("timeout", delivery_uncertain=True)
        with pytest.raises(ICTimeoutError):
            await install(controller)
    else:
        await install(controller, verification_timeout=0.01)
        await asyncio.sleep(0.02)
    phase = controller.firmware_update.phase
    reason = controller.firmware_update.reason
    connection.connected = False
    controller._on_disconnect(None)
    replacement = ScriptedConnection()
    controller._connection = replacement
    controller._firmware.attach(replacement)
    replacement.emit(FIXTURE["initial"])
    assert controller.firmware_update.phase == phase
    assert controller.firmware_update.reason == reason
    with pytest.raises(ICError, match="already requested"):
        await install(controller)
    assert not replacement.requests
    await controller.stop()


@pytest.mark.parametrize("params", [{"IN": "changed"}, {"VER": "changed"}])
async def test_transport_queue_rechecks_eligibility_at_write(supported: Any, params: Any) -> None:
    controller, connection = supported
    connection.before_dispatch = lambda: connection.emit(params)
    with pytest.raises(ICError, match="eligibility changed"):
        await install(controller)
    assert not connection.requests
    assert not controller._firmware.dispatched
    assert controller.firmware_update.reason == "request_not_sent"


async def test_verification_cannot_race_pending_ack(supported: Any) -> None:
    controller, connection = supported
    connection.gate = asyncio.Event()
    task = asyncio.create_task(install(controller))
    await connection.started.wait()
    with pytest.raises(ICError, match="awaiting its acknowledgement"):
        await controller.verify_firmware_update()
    connection.gate.set()
    await task
    assert controller.firmware_update.phase == Phase.ACKNOWLEDGED
    assert len(connection.requests) == 1
    await controller.stop()


async def test_acknowledgement_timeout_is_uncertain(supported: Any) -> None:
    controller, connection = supported
    connection.gate = asyncio.Event()
    with pytest.raises(TimeoutError):
        await install(controller, verification_timeout=0.01)
    assert controller.firmware_update.phase == Phase.UNKNOWN
    assert controller.firmware_update.reason == "request_outcome_uncertain"
    assert len(connection.requests) == 1


async def test_verification_read_failure_propagates(supported: Any) -> None:
    controller, connection = supported
    await install(controller)
    connection.error = ICTimeoutError("read timeout")
    with pytest.raises(ICTimeoutError):
        await controller.verify_firmware_update()
    assert controller.firmware_update.phase == Phase.UNKNOWN
    assert controller.firmware_update.reason == "verification_read_failed"
    assert not controller._firmware._timer
    await controller.stop()


async def test_stopped_watcher_sees_disconnected_state(supported: Any) -> None:
    controller, _ = supported
    await install(controller)
    watcher = controller.watch_firmware_update()
    await anext(watcher)
    await controller.stop()
    state = await anext(watcher)
    assert not state.connected
    assert state.phase == Phase.UNKNOWN
    assert state.reason == "controller_stopped"
    await watcher.aclose()


async def test_conflicting_new_notification_prevents_stale_verification(supported: Any) -> None:
    controller, connection = supported
    await install(controller)
    connection.gate = asyncio.Event()
    connection.started.clear()
    connection.response = {
        "response": "200",
        "objectList": [{"objnam": "_5451", "params": {"VER": FIXTURE["target_version"]}}],
    }
    task = asyncio.create_task(controller.verify_firmware_update())
    await connection.started.wait()
    connection.emit({"VER": "newer-conflicting-version"})
    connection.gate.set()
    state = await task
    assert state.phase == Phase.UNKNOWN
    assert state.verified_version is None
    assert state.installed_version == "newer-conflicting-version"
    assert state.reason == "version_changed_during_verification"
    assert controller.metrics.requests_sent == 2
    assert controller.metrics.requests_completed == 2
    await controller.stop()
