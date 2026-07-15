"""Tests for the evidence-bounded light-group Color Sync lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import copy
from dataclasses import dataclass
from typing import Any

import pytest

import pyintellicenter._light_group as light_group
from pyintellicenter import (
    ICCommandError,
    ICConnectionError,
    ICError,
    ICLightGroupError,
    ICModelController,
    ICSystemInfo,
    PoolModel,
)

PROJECTION_KEYS = (
    "OBJTYP",
    "SUBTYP",
    "PARENT",
    "CIRCUIT",
    "LISTORD",
    "STATUS",
    "USE",
    "SYNC",
    "SET",
    "SWIM",
    "VER",
    "SERVICE",
)


@dataclass(frozen=True)
class RecordedCall:
    """One scripted connection request."""

    command: str
    kwargs: dict[str, Any]
    request_timeout: float | None


class ScriptedConnection:
    """Deterministic connection fake with explicit transport boundaries."""

    def __init__(
        self,
        projections: list[dict[str, Any]],
        *,
        action_frames: list[dict[str, Any]],
    ) -> None:
        self.connected = True
        self.calls: list[RecordedCall] = []
        self.observers: list[Any] = []
        self.projections = projections
        self.action_frames = action_frames
        self.action_response: dict[str, Any] = {
            "messageID": "4",
            "response": "200",
            "opaqueVendorField": {"kept": True},
        }
        self._sequence = 0
        self._get_index = 0
        self._message_id = 0
        self._command_counts: dict[str, int] = {}
        self.closed = asyncio.get_running_loop().create_future()
        self.capture_count = 0
        self.remove_count = 0
        self.before_response_frames: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self.before_write_frames: list[dict[str, Any]] = []
        self.between_write_frames: list[dict[str, Any]] = []
        self.action_gate: asyncio.Event | None = None
        self.action_response_gate: asyncio.Event | None = None
        self.action_error: BaseException | None = None
        self.scripts: dict[tuple[str, int], Any] = {}

    def _capture_closed_future(self) -> asyncio.Future[None]:
        self.capture_count += 1
        return self.closed

    def add_notification_observer(self, observer: Any) -> Any:
        self.observers.append(observer)
        removed = False

        def remove() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            self.remove_count += 1
            self.observers.remove(observer)

        return remove

    def emit(self, frame: dict[str, Any]) -> None:
        self._sequence += 1
        for observer in tuple(self.observers):
            observer(self._sequence, frame)

    def close_generation(self) -> None:
        if not self.closed.done():
            self.closed.set_result(None)

    def reconnect_same_instance(self) -> asyncio.Future[None]:
        old = self.closed
        self.close_generation()
        self.closed = asyncio.get_running_loop().create_future()
        self.connected = True
        return old

    def _emit_before_response(self, command: str, occurrence: int) -> None:
        for frame in self.before_response_frames.get((command, occurrence), []):
            self.emit(frame)

    def _subscription_response(self, request: list[dict[str, Any]]) -> dict[str, Any]:
        raw_entries = {
            entry["objnam"]: entry["params"] for entry in self.projections[0]["objectList"]
        }
        object_list = []
        for item in request:
            params = raw_entries[item["objnam"]]
            object_list.append(
                {
                    "objnam": item["objnam"],
                    "params": {key: params[key] for key in item["keys"] if key in params},
                }
            )
        return {
            "messageID": str(self._message_id),
            "response": "200",
            "objectList": object_list,
        }

    async def send_request(
        self,
        command: str,
        request_timeout: float | None = None,
        *,
        _before_write_callback: Any = None,
        _after_write_callback: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(RecordedCall(command, kwargs, request_timeout))
        self._message_id += 1
        occurrence = self._command_counts.get(command, 0) + 1
        self._command_counts[command] = occurrence

        script = self.scripts.get((command, occurrence))
        if script is not None:
            return await script(
                self,
                _before_write_callback,
                _after_write_callback,
                kwargs,
            )

        if command != "SetParamList":
            if _before_write_callback is not None:
                _before_write_callback(self._sequence, asyncio.get_running_loop().time())
            if _after_write_callback is not None:
                _after_write_callback(self._sequence)

        if command == "GetParamList":
            response = self.projections[self._get_index]
            self._get_index += 1
            self._emit_before_response(command, occurrence)
            return {
                "messageID": str(self._message_id),
                "response": "200",
                **response,
            }
        if command == "RequestParamList":
            self._emit_before_response(command, occurrence)
            return self._subscription_response(kwargs["objectList"])
        if command == "SetParamList":
            for frame in self.before_write_frames:
                self.emit(frame)
            if _before_write_callback is not None:
                _before_write_callback(self._sequence, asyncio.get_running_loop().time())
            for frame in self.between_write_frames:
                self.emit(frame)
            if self.action_gate is not None:
                await self.action_gate.wait()
            if _after_write_callback is not None:
                _after_write_callback(self._sequence)
            for frame in self.action_frames:
                self.emit(frame)
            if self.action_response_gate is not None:
                await self.action_response_gate.wait()
            if self.action_error is not None:
                raise self.action_error
            self._emit_before_response(command, occurrence)
            return self.action_response
        self._emit_before_response(command, occurrence)
        return {"messageID": str(self._message_id), "response": "200"}


def _entry(objnam: str, **params: str) -> dict[str, Any]:
    return {"objnam": objnam, "params": params}


def make_projection(status: str) -> dict[str, Any]:
    """Build one complete hardware-shaped wildcard projection."""
    return {
        "objectList": [
            _entry("SYS", OBJTYP="SYSTEM", VER="1.064", SERVICE="AUTO"),
            _entry(
                "GROUP",
                OBJTYP="CIRCUIT",
                SUBTYP="LITSHO",
                PARENT="PARENT",
                STATUS=status,
                USE="USE",
                SYNC="OFF",
                SET="OFF",
                SWIM="OFF",
            ),
            _entry(
                "CHILD_A",
                OBJTYP="CIRCUIT",
                SUBTYP="GLOW",
                PARENT="GROUP",
                STATUS=status,
                USE="USE",
            ),
            _entry(
                "CHILD_B",
                OBJTYP="CIRCUIT",
                SUBTYP="GLOW",
                PARENT="GROUP",
                STATUS=status,
                USE="USE",
            ),
            _entry("AUX", OBJTYP="CIRCUIT", SUBTYP="LIGHT", STATUS="OFF"),
            _entry(
                "OTHER_GROUP",
                OBJTYP="CIRCUIT",
                SUBTYP="LITSHO",
                STATUS="OFF",
                SYNC="OFF",
                SET="OFF",
                SWIM="OFF",
            ),
            _entry(
                "ROW_A",
                OBJTYP="CIRCGRP",
                PARENT="GROUP",
                CIRCUIT="CHILD_A",
                LISTORD="1",
            ),
            _entry(
                "ROW_B",
                OBJTYP="CIRCGRP",
                PARENT="GROUP",
                CIRCUIT="CHILD_B",
                LISTORD="2",
                USE="00000",
            ),
            _entry(
                "OTHER_ROW",
                OBJTYP="CIRCGRP",
                PARENT="OTHER_GROUP",
                CIRCUIT="AUX",
                LISTORD="1",
                USE="USE",
            ),
            _entry("IGNORED", OBJTYP="MODULE", STATUS="STATUS"),
        ]
    }


def final_projection(status: str) -> dict[str, Any]:
    projection = make_projection(status)
    for entry in projection["objectList"]:
        if entry["objnam"] in {"GROUP", "CHILD_A", "CHILD_B"}:
            entry["params"]["STATUS"] = "ON"
    return projection


def action_frames(status: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    if status == "OFF":
        frames.extend(
            [
                {"command": "NotifyList", "objectList": [_entry("CHILD_B", STATUS="ON")]},
                {"command": "NotifyList", "objectList": [_entry("GROUP", STATUS="ON")]},
                {"command": "NotifyList", "objectList": [_entry("CHILD_A", STATUS="ON")]},
            ]
        )
    frames.extend(
        [
            {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]},
            {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="OFF")]},
        ]
    )
    return frames


def make_controller(
    status: str = "OFF",
    *,
    firmware: str = "1.064",
    settled: dict[str, Any] | None = None,
    frames: list[dict[str, Any]] | None = None,
) -> tuple[ICModelController, ScriptedConnection]:
    controller = make_cached_controller(status, firmware=firmware)
    connection = ScriptedConnection(
        [make_projection(status), settled or make_projection(status), final_projection(status)],
        action_frames=frames if frames is not None else action_frames(status),
    )
    controller._connection = connection  # type: ignore[assignment]
    return controller, connection


def make_cached_controller(
    status: str = "OFF",
    *,
    firmware: str = "1.064",
) -> ICModelController:
    return make_cached_controller_from_projection(make_projection(status), firmware=firmware)


def make_cached_controller_from_projection(
    cached: dict[str, Any],
    *,
    firmware: str = "1.064",
) -> ICModelController:
    model = PoolModel()
    for entry in cached["objectList"]:
        model.add_object(entry["objnam"], dict(entry["params"]))

    controller = ICModelController("192.0.2.1", model)
    controller._system_info = ICSystemInfo(
        "SYS",
        {
            "PROPNAME": "Pool",
            "VER": firmware,
            "MODE": "ENGLISH",
            "SNAME": "Pool",
        },
    )
    return controller


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["tcp", "websocket"])
@pytest.mark.parametrize("status", ["OFF", "ON"])
async def test_run_light_group_sync_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
    status: str,
) -> None:
    controller, connection = make_controller(status)
    controller._transport = transport  # transport parity is exercised by the scripted boundaries
    monkeypatch.setattr(light_group, "SUBSCRIPTION_SETTLE_SECONDS", 0)
    monkeypatch.setattr(light_group, "SYNC_POST_TERMINAL_OBSERVATION_SECONDS", 0)

    ack = await controller.run_light_group_sync("GROUP")

    assert ack is connection.action_response
    assert [call.command for call in connection.calls] == [
        "GetParamList",
        "RequestParamList",
        "GetParamList",
        "SetParamList",
        "GetParamList",
    ]
    assert connection.calls[3].kwargs == {
        "objectList": [{"objnam": "GROUP", "params": {"SYNC": "ON"}}]
    }
    assert connection.calls[3].request_timeout == 60.0
    for call in (connection.calls[0], connection.calls[2], connection.calls[4]):
        assert call.kwargs == {
            "condition": "",
            "objectList": [{"objnam": "INCR", "keys": list(PROJECTION_KEYS)}],
        }
    subscription = connection.calls[1].kwargs["objectList"]
    assert sum(len(item["keys"]) for item in subscription) <= 50
    assert connection.observers == []
    assert controller._light_group_mutation_pending is False
    assert controller._light_group_mutation_lease is None


@pytest.mark.asyncio
@pytest.mark.parametrize("firmware", ["", "IC: 1.064", "1.064 ", "1.064-build", "3.008"])
async def test_cached_firmware_gate_rejects_before_io(firmware: str) -> None:
    controller, connection = make_controller(firmware=firmware)

    with pytest.raises(ValueError, match="firmware"):
        await controller.run_light_group_sync("GROUP")

    assert connection.calls == []


@pytest.mark.asyncio
async def test_second_projection_mismatch_is_ordinary_pre_dispatch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settled = make_projection("OFF")
    next(entry for entry in settled["objectList"] if entry["objnam"] == "AUX")["params"][
        "STATUS"
    ] = "ON"
    controller, connection = make_controller(settled=settled)
    monkeypatch.setattr(light_group, "SUBSCRIPTION_SETTLE_SECONDS", 0)

    with pytest.raises(ICError, match="preflight mismatch") as raised:
        await controller.run_light_group_sync("GROUP")

    assert not isinstance(raised.value, ICLightGroupError)
    assert all(call.command != "SetParamList" for call in connection.calls)
    assert connection.observers == []


def test_light_group_error_metadata_is_read_only_and_safe() -> None:
    error = ICLightGroupError(
        "failed",
        phase="terminal",
        response_received=True,
        acknowledged=True,
        onset_seen=True,
    )

    assert error.phase == "terminal"
    assert error.dispatch_started is True
    assert error.response_received is True
    assert error.acknowledged is True
    assert error.onset_seen is True
    assert "terminal" in repr(error)
    assert "failed" not in repr(error)
    with pytest.raises(AttributeError):
        error.phase = "onset"  # type: ignore[misc]


def test_only_scoped_sync_api_exists() -> None:
    assert hasattr(ICModelController, "run_light_group_sync")
    assert not hasattr(ICModelController, "run_light_group_command")
    assert not hasattr(ICModelController, "run_light_group_swim")
    assert not hasattr(ICModelController, "set_light_group_member_position")


def _tracker(status: str = "OFF") -> light_group.LightGroupSyncTracker:
    controller = make_cached_controller(status)
    topology = light_group.build_topology(controller, "GROUP")
    tracker = light_group.LightGroupSyncTracker(topology)
    tracker.set_prewrite_baseline(light_group.parse_projection(make_projection(status), topology))
    return tracker


def _subscription_response(
    request: list[dict[str, Any]],
    projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_entries = {
        entry["objnam"]: entry["params"]
        for entry in (projection or make_projection("OFF"))["objectList"]
    }
    return {
        "messageID": "2",
        "response": "200",
        "objectList": [
            {
                "objnam": item["objnam"],
                "params": {
                    key: raw_entries[item["objnam"]][key]
                    for key in item["keys"]
                    if key in raw_entries[item["objnam"]]
                },
            }
            for item in request
        ],
    }


@pytest.mark.parametrize(
    "case",
    [
        "missing_target",
        "target_is_row",
        "ordinary_target",
        "zero_rows",
        "one_row",
        "three_rows",
        "duplicate_child_reference",
        "missing_child",
        "wrong_child_type",
        "wrong_child_subtype",
        "listord_null",
        "listord_placeholder",
        "listord_nonnumeric",
        "listord_negative",
    ],
)
def test_cached_topology_rejects_every_unsupported_shape(case: str) -> None:
    cached = make_projection("OFF")
    target = "GROUP"
    entries = cached["objectList"]
    by_name = {entry["objnam"]: entry for entry in entries}
    if case == "missing_target":
        cached["objectList"] = [entry for entry in entries if entry["objnam"] != "GROUP"]
    elif case == "target_is_row":
        target = "ROW_A"
    elif case == "ordinary_target":
        by_name["GROUP"]["params"]["SUBTYP"] = "LIGHT"
    elif case == "zero_rows":
        cached["objectList"] = [
            entry for entry in entries if entry["objnam"] not in {"ROW_A", "ROW_B"}
        ]
    elif case == "one_row":
        cached["objectList"] = [entry for entry in entries if entry["objnam"] != "ROW_B"]
    elif case == "three_rows":
        cached["objectList"].append(
            _entry(
                "ROW_C",
                OBJTYP="CIRCGRP",
                PARENT="GROUP",
                CIRCUIT="AUX",
                LISTORD="3",
            )
        )
    elif case == "duplicate_child_reference":
        by_name["ROW_B"]["params"]["CIRCUIT"] = "CHILD_A"
    elif case == "missing_child":
        by_name["ROW_B"]["params"]["CIRCUIT"] = "MISSING"
    elif case == "wrong_child_type":
        by_name["CHILD_B"]["params"]["OBJTYP"] = "MODULE"
    elif case == "wrong_child_subtype":
        by_name["CHILD_B"]["params"]["SUBTYP"] = "INTELLI"
    elif case == "listord_null":
        by_name["ROW_A"]["params"]["LISTORD"] = "00000"
    elif case == "listord_placeholder":
        by_name["ROW_A"]["params"]["LISTORD"] = "LISTORD"
    elif case == "listord_nonnumeric":
        by_name["ROW_A"]["params"]["LISTORD"] = "first"
    elif case == "listord_negative":
        by_name["ROW_A"]["params"]["LISTORD"] = "-1"

    controller = make_cached_controller_from_projection(cached)

    with pytest.raises(ValueError):
        light_group.build_topology(controller, target)


def test_cached_topology_requires_cached_system_info() -> None:
    controller = make_cached_controller()
    controller._system_info = None

    with pytest.raises(ValueError, match="firmware"):
        light_group.build_topology(controller, "GROUP")


@pytest.mark.asyncio
async def test_multiple_cached_systems_reject_before_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = make_projection("OFF")
    cached["objectList"].append(_entry("SYS_2", OBJTYP="SYSTEM", VER="1.064", SERVICE="AUTO"))
    controller = make_cached_controller_from_projection(cached)
    connection = ScriptedConnection(
        [make_projection("OFF"), make_projection("OFF"), final_projection("OFF")],
        action_frames=action_frames("OFF"),
    )
    controller._connection = connection  # type: ignore[assignment]
    _fast_lifecycle(monkeypatch)

    with pytest.raises(ValueError, match="cached system"):
        await controller.run_light_group_sync("GROUP")

    assert connection.calls == []


def test_cached_topology_and_projection_are_frozen_tuple_owned() -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    projection = light_group.parse_projection(make_projection("OFF"), topology)

    assert isinstance(topology.target_rows, tuple)
    assert isinstance(projection.circuits, tuple)
    with pytest.raises(AttributeError):
        topology.target_objnam = "OTHER"  # type: ignore[misc]


@pytest.mark.parametrize(
    "case",
    [
        "non_dict_response",
        "missing_object_list",
        "non_list_object_list",
        "non_dict_entry",
        "missing_objnam",
        "empty_objnam",
        "non_dict_params",
        "duplicate_objnam",
        "unknown_missing_type",
        "unknown_placeholder_type",
        "unknown_null_type",
        "new_relevant_object",
        "missing_relevant_object",
        "missing_system",
        "multiple_systems",
        "changed_child_subtype",
        "missing_circuit_status",
        "missing_row_parent",
        "row_parent_placeholder",
        "row_parent_null",
    ],
)
def test_projection_rejects_malformed_envelope_inventory_and_topology(case: str) -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    projection: Any = make_projection("OFF")
    if case == "non_dict_response":
        projection = []
    elif case == "missing_object_list":
        projection = {}
    elif case == "non_list_object_list":
        projection["objectList"] = {}
    elif case == "non_dict_entry":
        projection["objectList"].append("bad")
    elif case == "missing_objnam":
        projection["objectList"][-1].pop("objnam")
    elif case == "empty_objnam":
        projection["objectList"][-1]["objnam"] = ""
    elif case == "non_dict_params":
        projection["objectList"][-1]["params"] = []
    elif case == "duplicate_objnam":
        projection["objectList"].append(copy.deepcopy(projection["objectList"][0]))
    elif case == "unknown_missing_type":
        projection["objectList"][-1]["params"].pop("OBJTYP")
    elif case == "unknown_placeholder_type":
        projection["objectList"][-1]["params"]["OBJTYP"] = "OBJTYP"
    elif case == "unknown_null_type":
        projection["objectList"][-1]["params"]["OBJTYP"] = "00000"
    elif case == "new_relevant_object":
        projection["objectList"].append(
            _entry("NEW", OBJTYP="CIRCUIT", SUBTYP="LIGHT", STATUS="OFF")
        )
    elif case == "missing_relevant_object":
        projection["objectList"] = [
            entry for entry in projection["objectList"] if entry["objnam"] != "AUX"
        ]
    elif case == "missing_system":
        projection["objectList"] = [
            entry for entry in projection["objectList"] if entry["objnam"] != "SYS"
        ]
    elif case == "multiple_systems":
        projection["objectList"].append(
            _entry("SYS_2", OBJTYP="SYSTEM", VER="1.064", SERVICE="AUTO")
        )
    elif case == "changed_child_subtype":
        next(entry for entry in projection["objectList"] if entry["objnam"] == "CHILD_A")["params"][
            "SUBTYP"
        ] = "INTELLI"
    elif case == "missing_circuit_status":
        next(entry for entry in projection["objectList"] if entry["objnam"] == "AUX")["params"].pop(
            "STATUS"
        )
    elif case == "missing_row_parent":
        next(entry for entry in projection["objectList"] if entry["objnam"] == "ROW_A")[
            "params"
        ].pop("PARENT")
    elif case == "row_parent_placeholder":
        next(entry for entry in projection["objectList"] if entry["objnam"] == "ROW_A")["params"][
            "PARENT"
        ] = "PARENT"
    elif case == "row_parent_null":
        next(entry for entry in projection["objectList"] if entry["objnam"] == "ROW_A")["params"][
            "PARENT"
        ] = "00000"

    with pytest.raises(ICError):
        light_group.parse_projection(projection, topology)


def test_projection_ignores_only_explicit_well_formed_unrelated_types() -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    projection = make_projection("OFF")
    projection["objectList"].append(_entry("EXTRA", OBJTYP="MODULE", STATUS="ON"))

    parsed = light_group.parse_projection(projection, topology)

    assert all(item.objnam != "EXTRA" for item in parsed.circuits)


@pytest.mark.parametrize("spelling", ["omitted", "USE", "00000"])
def test_row_use_absence_spellings_normalize_to_equal_projection(spelling: str) -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    projection = make_projection("OFF")
    row = next(entry for entry in projection["objectList"] if entry["objnam"] == "ROW_A")
    if spelling == "omitted":
        row["params"].pop("USE", None)
    else:
        row["params"]["USE"] = spelling

    parsed = light_group.parse_projection(projection, topology)

    assert next(item for item in parsed.rows if item.objnam == "ROW_A").use is None


@pytest.mark.parametrize(
    "case",
    [
        "wrong_version",
        "wrong_service",
        "group_flag_on",
        "mixed_target_status",
        "noncanonical_target_status",
    ],
)
def test_initial_projection_rejects_every_fresh_global_gate(case: str) -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    projection = make_projection("OFF")
    by_name = {entry["objnam"]: entry for entry in projection["objectList"]}
    if case == "wrong_version":
        by_name["SYS"]["params"]["VER"] = "1.064 "
    elif case == "wrong_service":
        by_name["SYS"]["params"]["SERVICE"] = "MANUAL"
    elif case == "group_flag_on":
        by_name["OTHER_GROUP"]["params"]["SET"] = "ON"
    elif case == "mixed_target_status":
        by_name["CHILD_A"]["params"]["STATUS"] = "ON"
    elif case == "noncanonical_target_status":
        by_name["GROUP"]["params"]["STATUS"] = "READY"
        by_name["CHILD_A"]["params"]["STATUS"] = "READY"
        by_name["CHILD_B"]["params"]["STATUS"] = "READY"

    parsed = light_group.parse_projection(projection, topology)
    with pytest.raises(ICError):
        light_group.validate_initial_projection(parsed, topology)


@pytest.mark.parametrize(
    "case",
    [
        "target_off",
        "unrelated_status",
        "target_set",
        "other_group_sync",
        "row_use",
        "system_service",
    ],
)
def test_final_projection_rejects_every_authoritative_mismatch(case: str) -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    baseline = light_group.parse_projection(make_projection("OFF"), topology)
    final_raw = final_projection("OFF")
    by_name = {entry["objnam"]: entry for entry in final_raw["objectList"]}
    if case == "target_off":
        by_name["CHILD_A"]["params"]["STATUS"] = "OFF"
    elif case == "unrelated_status":
        by_name["AUX"]["params"]["STATUS"] = "ON"
    elif case == "target_set":
        by_name["GROUP"]["params"]["SET"] = "ON"
    elif case == "other_group_sync":
        by_name["OTHER_GROUP"]["params"]["SYNC"] = "ON"
    elif case == "row_use":
        by_name["ROW_A"]["params"]["USE"] = "REAL"
    elif case == "system_service":
        by_name["SYS"]["params"]["SERVICE"] = "MANUAL"
    final = light_group.parse_projection(final_raw, topology)

    with pytest.raises(ICError):
        light_group.validate_final_projection(final, baseline, topology)


def test_subscription_batches_have_deterministic_exact_coverage() -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")

    first = light_group.build_subscription_batches(topology)
    second = light_group.build_subscription_batches(topology)

    assert first == second
    assert all(sum(len(item["keys"]) for item in batch) <= 50 for batch in first)
    covered = [(item["objnam"], key) for batch in first for item in batch for key in item["keys"]]
    assert len(covered) == len(set(covered))
    assert {objnam for objnam, _key in covered} == {
        topology.system_objnam,
        *topology.circuit_objnams,
        *topology.row_objnams,
    }


def test_subscription_batches_split_before_fifty_key_overflow() -> None:
    cached = make_projection("OFF")
    for index in range(3):
        cached["objectList"].append(
            _entry(
                f"EXTRA_{index}",
                OBJTYP="CIRCUIT",
                SUBTYP="LIGHT",
                STATUS="OFF",
            )
        )
    controller = make_cached_controller_from_projection(cached)
    topology = light_group.build_topology(controller, "GROUP")
    baseline = light_group.parse_projection(cached, topology)

    batches = light_group.build_subscription_batches(topology)

    assert len(batches) >= 2
    assert all(sum(len(item["keys"]) for item in batch) <= 50 for batch in batches)
    covered = [(item["objnam"], key) for batch in batches for item in batch for key in item["keys"]]
    assert len(covered) == len(set(covered))
    for batch in batches:
        light_group.validate_subscription_response(
            _subscription_response(batch, cached), batch, baseline, topology
        )


@pytest.mark.parametrize(
    "case",
    [
        "non_200",
        "missing_message_id",
        "empty_message_id",
        "missing_object_list",
        "empty_object_list",
        "non_dict_entry",
        "duplicate_object",
        "unexpected_object",
        "unexpected_key",
        "missing_object",
        "missing_mandatory_key",
        "placeholder_mandatory",
        "null_mandatory",
        "malformed_optional",
        "changed_optional",
    ],
)
def test_subscription_initialization_rejects_malformed_or_mismatched_coverage(
    case: str,
) -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    baseline = light_group.parse_projection(make_projection("OFF"), topology)
    request = light_group.build_subscription_batches(topology)[0]
    response = _subscription_response(request)
    object_list = response["objectList"]
    if case == "non_200":
        response["response"] = "500"
    elif case == "missing_message_id":
        response.pop("messageID")
    elif case == "empty_message_id":
        response["messageID"] = ""
    elif case == "missing_object_list":
        response.pop("objectList")
    elif case == "empty_object_list":
        response["objectList"] = []
    elif case == "non_dict_entry":
        object_list[0] = "bad"
    elif case == "duplicate_object":
        object_list.append(copy.deepcopy(object_list[0]))
    elif case == "unexpected_object":
        object_list[0]["objnam"] = "EXTRA"
    elif case == "unexpected_key":
        object_list[0]["params"]["EXTRA"] = "ON"
    elif case == "missing_object":
        object_list.pop()
    elif case == "missing_mandatory_key":
        next(entry for entry in object_list if entry["objnam"] == "ROW_A")["params"].pop("PARENT")
    elif case == "placeholder_mandatory":
        next(entry for entry in object_list if entry["objnam"] == "ROW_A")["params"]["PARENT"] = (
            "PARENT"
        )
    elif case == "null_mandatory":
        next(entry for entry in object_list if entry["objnam"] == "ROW_A")["params"]["PARENT"] = (
            "00000"
        )
    elif case == "malformed_optional":
        next(entry for entry in object_list if entry["objnam"] == "AUX")["params"]["PARENT"] = []
    elif case == "changed_optional":
        next(entry for entry in object_list if entry["objnam"] == "AUX")["params"]["PARENT"] = (
            "REAL"
        )

    with pytest.raises(ICError):
        light_group.validate_subscription_response(response, request, baseline, topology)


@pytest.mark.parametrize("spelling", ["omitted", None, "PARENT", "00000"])
def test_subscription_optional_absence_spellings_equal_baseline(spelling: str | None) -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    baseline = light_group.parse_projection(make_projection("OFF"), topology)
    request = light_group.build_subscription_batches(topology)[0]
    response = _subscription_response(request)
    params = next(entry for entry in response["objectList"] if entry["objnam"] == "AUX")["params"]
    if spelling == "omitted":
        params.pop("PARENT", None)
    else:
        params["PARENT"] = spelling

    light_group.validate_subscription_response(response, request, baseline, topology)


@pytest.mark.parametrize("spelling", ["omitted", None, "USE", "00000"])
def test_subscription_row_use_absence_spellings_equal_baseline(spelling: str | None) -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    baseline = light_group.parse_projection(make_projection("OFF"), topology)
    request = light_group.build_subscription_batches(topology)[0]
    response = _subscription_response(request)
    params = next(entry for entry in response["objectList"] if entry["objnam"] == "ROW_A")["params"]
    if spelling == "omitted":
        params.pop("USE", None)
    else:
        params["USE"] = spelling

    light_group.validate_subscription_response(response, request, baseline, topology)


def test_subscription_row_use_real_value_is_retained_and_compared() -> None:
    projection = make_projection("OFF")
    next(entry for entry in projection["objectList"] if entry["objnam"] == "ROW_A")["params"][
        "USE"
    ] = "REAL"
    controller = make_cached_controller_from_projection(projection)
    topology = light_group.build_topology(controller, "GROUP")
    baseline = light_group.parse_projection(projection, topology)
    request = light_group.build_subscription_batches(topology)[0]
    response = _subscription_response(request, projection)

    light_group.validate_subscription_response(response, request, baseline, topology)
    next(entry for entry in response["objectList"] if entry["objnam"] == "ROW_A")["params"][
        "USE"
    ] = "CHANGED"
    with pytest.raises(ICError, match="differs from baseline"):
        light_group.validate_subscription_response(response, request, baseline, topology)


@pytest.mark.parametrize(
    ("objnam", "key"),
    [
        ("SYS", "VER"),
        ("GROUP", "STATUS"),
        ("GROUP", "SYNC"),
        ("ROW_A", "PARENT"),
        ("ROW_A", "CIRCUIT"),
        ("ROW_A", "LISTORD"),
    ],
)
def test_projection_rejects_null_reference_in_every_mandatory_field(
    objnam: str,
    key: str,
) -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    projection = make_projection("OFF")
    next(entry for entry in projection["objectList"] if entry["objnam"] == objnam)["params"][
        key
    ] = "00000"

    with pytest.raises(ICError, match="mandatory"):
        light_group.parse_projection(projection, topology)


@pytest.mark.parametrize("value", [None, "PARENT", "00000"])
def test_projection_normalizes_declared_optional_absence(value: str | None) -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    projection = make_projection("OFF")
    aux = next(entry for entry in projection["objectList"] if entry["objnam"] == "AUX")
    aux["params"]["PARENT"] = value

    parsed = light_group.parse_projection(projection, topology)

    assert next(item for item in parsed.circuits if item.objnam == "AUX").parent is None


def test_projection_rejects_non_string_non_null_optional_value() -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    projection = make_projection("OFF")
    aux = next(entry for entry in projection["objectList"] if entry["objnam"] == "AUX")
    aux["params"]["PARENT"] = 7

    with pytest.raises(ICError, match="optional PARENT"):
        light_group.parse_projection(projection, topology)


@pytest.mark.parametrize(
    "frame",
    [
        {"command": "NotifyList", "objectList": [_entry("GROUP", STATUS="ON")]},
        {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]},
    ],
)
def test_every_projected_target_delta_before_write_is_irreversible(frame: dict[str, Any]) -> None:
    tracker = _tracker()

    tracker.observe(1, frame)

    with pytest.raises(ICError, match="invariant"):
        tracker.raise_if_failed()
    assert not tracker.write_started.is_set()


def test_notification_entries_are_processed_in_wire_order() -> None:
    tracker = _tracker()

    tracker.observe(
        1,
        {
            "command": "NotifyList",
            "objectList": [
                _entry("AUX", STATUS="ON"),
                _entry("AUX", STATUS="OFF"),
            ],
        },
    )

    with pytest.raises(ICError, match="AUX.STATUS"):
        tracker.raise_if_failed()


def test_equal_duplicate_notification_entries_are_harmless() -> None:
    tracker = _tracker()

    tracker.observe(
        1,
        {
            "command": "NotifyList",
            "objectList": [
                _entry("AUX", STATUS="OFF"),
                _entry("AUX", STATUS="OFF"),
            ],
        },
    )

    tracker.raise_if_failed()


def test_prebaseline_notification_is_copied_and_replayed() -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    tracker = light_group.LightGroupSyncTracker(topology)
    frame = {"command": "NotifyList", "objectList": [_entry("AUX", STATUS="ON")]}

    tracker.observe(1, frame)
    frame["objectList"][0]["params"]["STATUS"] = "OFF"
    tracker.set_prewrite_baseline(light_group.parse_projection(make_projection("OFF"), topology))

    with pytest.raises(ICError, match="AUX.STATUS"):
        tracker.raise_if_failed()


def test_prebaseline_notification_overflow_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = make_cached_controller()
    topology = light_group.build_topology(controller, "GROUP")
    tracker = light_group.LightGroupSyncTracker(topology)
    monkeypatch.setattr(light_group, "MAX_PREBASELINE_NOTIFICATIONS", 2)
    frame = {"command": "NotifyList", "objectList": [_entry("AUX", STATUS="OFF")]}

    tracker.observe(1, frame)
    tracker.observe(2, frame)
    tracker.observe(3, frame)

    with pytest.raises(ICError, match="buffer overflow"):
        tracker.raise_if_failed()


@pytest.mark.parametrize("post_dispatch", [False, True])
@pytest.mark.parametrize(
    "frame",
    [
        {},
        {"command": "NotifyList", "objectList": {}},
        {"command": "NotifyList", "objectList": ["bad"]},
        {"command": "NotifyList", "objectList": [{"params": {"STATUS": "ON"}}]},
        {"command": "NotifyList", "objectList": [{"objnam": 7, "params": {}}]},
        {"command": "NotifyList", "objectList": [{"objnam": "AUX", "params": []}]},
        {"command": "NotifyList", "objectList": [_entry("AUX", STATUS="STATUS")]},
        {"command": "NotifyList", "objectList": [_entry("AUX", STATUS="00000")]},
        {"command": "NotifyList", "objectList": [_entry("AUX", PARENT=[])]},
        {"command": "NotifyList", "objectList": [_entry("NEW", STATUS="ON")]},
        {"command": "NotifyList", "objectList": [_entry("NEW", OBJTYP="CIRCUIT")]},
        {"command": "NotifyList", "objectList": [_entry("NEW", OBJTYP="00000")]},
        {"command": "NotifyList", "objectList": [_entry("IGNORED", OBJTYP=None)]},
        {"command": "NotifyList", "objectList": [_entry("IGNORED", OBJTYP="00000")]},
    ],
)
def test_malformed_raw_notifications_fail_synchronously_in_every_phase(
    frame: dict[str, Any],
    post_dispatch: bool,
) -> None:
    tracker = _tracker()
    if post_dispatch:
        tracker.mark_before_write(0, 10.0)
        tracker.mark_after_write(0)

    tracker.observe(1, frame)

    assert tracker.failure_event.is_set()
    with pytest.raises(ICError):
        tracker.raise_if_failed()


def test_first_tracker_failure_is_never_replaced() -> None:
    tracker = _tracker()
    tracker.observe(1, {"command": "NotifyList", "objectList": [_entry("AUX", STATUS="ON")]})
    first = tracker.failure

    tracker.observe(2, {})

    assert tracker.failure is first
    assert tracker.failure_event.is_set()


def test_cached_irrelevant_object_partial_updates_remain_ignored() -> None:
    tracker = _tracker()

    tracker.observe(1, {"command": "NotifyList", "objectList": [_entry("IGNORED", STATUS="ON")]})
    tracker.observe(
        2,
        {"command": "NotifyList", "objectList": [_entry("IGNORED", OBJTYP="MODULE")]},
    )

    tracker.raise_if_failed()


def test_irrelevant_object_transition_into_relevant_type_is_irreversible() -> None:
    tracker = _tracker()

    tracker.observe(
        1,
        {"command": "NotifyList", "objectList": [_entry("IGNORED", OBJTYP="CIRCUIT")]},
    )
    tracker.observe(
        2,
        {"command": "NotifyList", "objectList": [_entry("IGNORED", OBJTYP="MODULE")]},
    )

    with pytest.raises(ICError, match="relevance"):
        tracker.raise_if_failed()


def test_new_explicit_irrelevant_object_can_be_tracked_until_relevance_changes() -> None:
    tracker = _tracker()

    tracker.observe(
        1,
        {"command": "NotifyList", "objectList": [_entry("NEW", OBJTYP="SENSOR")]},
    )
    tracker.observe(2, {"command": "NotifyList", "objectList": [_entry("NEW", VALUE="7")]})
    tracker.raise_if_failed()
    tracker.observe(
        3,
        {"command": "NotifyList", "objectList": [_entry("NEW", OBJTYP="SYSTEM")]},
    )

    with pytest.raises(ICError, match="relevance"):
        tracker.raise_if_failed()


@pytest.mark.parametrize("objnam", ["GROUP", "AUX", "ROW_A"])
@pytest.mark.parametrize("spelling", [None, "USE", "00000"])
def test_optional_notification_absence_spellings_compare_semantically(
    objnam: str,
    spelling: str | None,
) -> None:
    tracker = _tracker()

    tracker.observe(
        1,
        {"command": "NotifyList", "objectList": [_entry(objnam, USE=spelling)]},
    )

    tracker.raise_if_failed()


@pytest.mark.parametrize("spelling", ["PARENT", "00000"])
def test_present_row_parent_placeholder_is_always_malformed(spelling: str) -> None:
    tracker = _tracker()

    tracker.observe(
        1,
        {"command": "NotifyList", "objectList": [_entry("ROW_A", PARENT=spelling)]},
    )

    with pytest.raises(ICError, match="mandatory"):
        tracker.raise_if_failed()


def test_partial_row_notification_may_omit_parent_and_use() -> None:
    tracker = _tracker()

    tracker.observe(
        1,
        {"command": "NotifyList", "objectList": [_entry("ROW_A", LISTORD="1")]},
    )

    tracker.raise_if_failed()


def test_before_write_uses_supplied_clock_and_fails_before_marking_dispatch() -> None:
    tracker = _tracker()
    tracker.observe(1, {"command": "NotifyList", "objectList": [_entry("AUX", STATUS="ON")]})

    with pytest.raises(ICError):
        tracker.mark_before_write(7, 123.5)

    assert not tracker.write_started.is_set()
    assert tracker.write_started_at is None
    assert tracker.action_deadline is None


def test_before_write_records_exact_absolute_deadline() -> None:
    tracker = _tracker()

    tracker.mark_before_write(7, 123.5)

    assert tracker.pre_send_sequence == 7
    assert tracker.write_started_at == 123.5
    assert tracker.action_deadline == 183.5
    assert tracker.write_started.is_set()


@pytest.mark.asyncio
async def test_pre_watermark_sync_cannot_qualify_but_status_invariants_stay_live() -> None:
    tracker = _tracker()
    tracker.mark_before_write(0, asyncio.get_running_loop().time())

    tracker.observe(1, {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]})
    tracker.observe(2, {"command": "NotifyList", "objectList": [_entry("GROUP", STATUS="ON")]})
    tracker.observe(3, {"command": "NotifyList", "objectList": [_entry("CHILD_A", STATUS="ON")]})

    assert not tracker.onset_event.is_set()
    tracker.raise_if_failed()


@pytest.mark.asyncio
async def test_sync_edges_must_be_strictly_after_watermark_and_ordered() -> None:
    tracker = _tracker()
    tracker.mark_before_write(0, asyncio.get_running_loop().time())
    tracker.mark_after_write(5)

    tracker.observe(5, {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]})
    tracker.observe(6, {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="OFF")]})
    assert not tracker.onset_event.is_set()
    assert not tracker.terminal_event.is_set()
    tracker.observe(7, {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]})
    assert tracker.onset_event.is_set()
    assert not tracker.terminal_event.is_set()
    tracker.observe(8, {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="OFF")]})

    assert tracker.terminal_event.is_set()
    assert tracker.terminal_time is not None


@pytest.mark.asyncio
async def test_post_terminal_sync_reentry_is_irreversible() -> None:
    tracker = _tracker()
    tracker.mark_before_write(0, asyncio.get_running_loop().time())
    tracker.mark_after_write(0)
    tracker.observe(1, {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]})
    tracker.observe(2, {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="OFF")]})
    tracker.observe(3, {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]})
    tracker.observe(4, {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="OFF")]})

    with pytest.raises(ICError, match="re-entered"):
        tracker.raise_if_failed()


@pytest.mark.asyncio
async def test_all_off_target_status_is_monotonic_per_object() -> None:
    tracker = _tracker("OFF")
    tracker.mark_before_write(0, asyncio.get_running_loop().time())

    tracker.observe(1, {"command": "NotifyList", "objectList": [_entry("CHILD_A", STATUS="OFF")]})
    tracker.observe(2, {"command": "NotifyList", "objectList": [_entry("CHILD_A", STATUS="ON")]})
    tracker.observe(3, {"command": "NotifyList", "objectList": [_entry("CHILD_A", STATUS="OFF")]})

    with pytest.raises(ICError, match="returned off"):
        tracker.raise_if_failed()


@pytest.mark.asyncio
async def test_all_on_target_may_never_report_off() -> None:
    tracker = _tracker("ON")
    tracker.mark_before_write(0, asyncio.get_running_loop().time())

    tracker.observe(1, {"command": "NotifyList", "objectList": [_entry("GROUP", STATUS="OFF")]})

    with pytest.raises(ICError, match="all-on"):
        tracker.raise_if_failed()


@pytest.mark.parametrize(
    "entry",
    [
        _entry("GROUP", USE="CHANGED"),
        _entry("GROUP", SET="ON"),
        _entry("GROUP", SWIM="ON"),
        _entry("AUX", STATUS="ON"),
        _entry("AUX", PARENT="CHANGED"),
        _entry("OTHER_GROUP", SYNC="ON"),
        _entry("ROW_A", CIRCUIT="CHILD_B"),
        _entry("ROW_A", LISTORD="2"),
        _entry("ROW_A", USE="REAL"),
        _entry("SYS", SERVICE="MANUAL"),
    ],
)
def test_post_dispatch_collateral_invariants_fail_immediately(entry: dict[str, Any]) -> None:
    tracker = _tracker()
    tracker.mark_before_write(0, 10.0)

    tracker.observe(1, {"command": "NotifyList", "objectList": [entry]})

    with pytest.raises(ICError, match="invariant"):
        tracker.raise_if_failed()


def _fast_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(light_group, "SUBSCRIPTION_SETTLE_SECONDS", 0)
    monkeypatch.setattr(light_group, "SYNC_POST_TERMINAL_OBSERVATION_SECONDS", 0)


def _capture_tracker(
    monkeypatch: pytest.MonkeyPatch,
) -> list[light_group.LightGroupSyncTracker]:
    real_tracker = light_group.LightGroupSyncTracker
    captured: list[light_group.LightGroupSyncTracker] = []

    def factory(
        topology: light_group.LightGroupTopology,
    ) -> light_group.LightGroupSyncTracker:
        tracker = real_tracker(topology)
        captured.append(tracker)
        return tracker

    monkeypatch.setattr(light_group, "LightGroupSyncTracker", factory)
    return captured


def _deadline_barrier(monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    expired = asyncio.Event()

    async def wait_deadline(_deadline: float) -> None:
        await expired.wait()

    monkeypatch.setattr(light_group, "_wait_deadline", wait_deadline)
    return expired


async def _eventually(predicate: Any) -> None:
    for _attempt in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["first", "subscription", "second"])
async def test_prewrite_observer_failure_wakes_each_network_gate(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    controller, connection = make_controller()
    _fast_lifecycle(monkeypatch)
    key = {
        "first": ("GetParamList", 1),
        "subscription": ("RequestParamList", 1),
        "second": ("GetParamList", 2),
    }[stage]
    connection.before_response_frames[key] = [
        {"command": "NotifyList", "objectList": [_entry("AUX", STATUS="ON")]}
    ]

    with pytest.raises(ICError, match="AUX.STATUS") as raised:
        await controller.run_light_group_sync("GROUP")

    assert not isinstance(raised.value, ICLightGroupError)
    assert all(call.command != "SetParamList" for call in connection.calls)
    assert connection.observers == []


@pytest.mark.asyncio
async def test_equal_notification_in_first_response_turn_is_harmless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller()
    _fast_lifecycle(monkeypatch)
    connection.before_response_frames[("GetParamList", 1)] = [
        {"command": "NotifyList", "objectList": [_entry("AUX", STATUS="OFF")]}
    ]

    ack = await controller.run_light_group_sync("GROUP")

    assert ack is connection.action_response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frame",
    [
        {},
        {"command": "NotifyList", "objectList": ["bad"]},
        {"command": "NotifyList", "objectList": [_entry("NEW", OBJTYP="CIRCUIT")]},
    ],
)
async def test_structural_prebaseline_failure_wakes_a_blocked_first_read(
    monkeypatch: pytest.MonkeyPatch,
    frame: dict[str, Any],
) -> None:
    controller, connection = make_controller()
    captured = _capture_tracker(monkeypatch)
    first_read_sent = asyncio.Event()

    async def blocked_first_read(
        conn: ScriptedConnection,
        before: Any,
        after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        before(conn._sequence, asyncio.get_running_loop().time())
        if after is not None:
            after(conn._sequence)
        first_read_sent.set()
        await asyncio.Event().wait()
        raise AssertionError

    connection.scripts[("GetParamList", 1)] = blocked_first_read
    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await first_read_sent.wait()
    try:
        connection.emit(frame)
        assert captured[0].failure_event.is_set()
        with pytest.raises(ICError):
            await task
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    assert connection.observers == []
    assert connection.remove_count == 1
    assert all(call.command != "SetParamList" for call in connection.calls)


@pytest.mark.asyncio
async def test_projected_change_while_action_waits_to_write_stays_pre_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller()
    _fast_lifecycle(monkeypatch)
    connection.before_write_frames = [
        {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]}
    ]

    with pytest.raises(ICError, match="GROUP.SYNC") as raised:
        await controller.run_light_group_sync("GROUP")

    assert not isinstance(raised.value, ICLightGroupError)
    assert len([call for call in connection.calls if call.command == "SetParamList"]) == 1
    assert connection.observers == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "phase", "response_received", "acknowledged", "onset_seen"),
    [
        ("no_response", "acknowledgement", False, False, False),
        ("onset_no_response", "acknowledgement", False, False, True),
        ("ack_no_onset", "onset", True, True, False),
        ("onset_no_terminal", "terminal", True, True, True),
        ("stalled_send", "acknowledgement", False, False, False),
    ],
)
async def test_absolute_action_deadline_reports_exact_certainty_metadata(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    phase: str,
    response_received: bool,
    acknowledged: bool,
    onset_seen: bool,
) -> None:
    controller, connection = make_controller(frames=[])
    monkeypatch.setattr(light_group, "SUBSCRIPTION_SETTLE_SECONDS", 0)
    deadline = _deadline_barrier(monkeypatch)
    captured = _capture_tracker(monkeypatch)
    never = asyncio.Event()
    if scenario in {"no_response", "onset_no_response"}:
        connection.action_response_gate = never
    if scenario in {"onset_no_response", "onset_no_terminal"}:
        connection.action_frames = [
            {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]}
        ]
    elif scenario == "stalled_send":
        connection.action_gate = never

    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await _eventually(lambda: bool(captured) and captured[0].write_started.is_set())
    tracker = captured[0]
    if scenario == "ack_no_onset":
        await _eventually(lambda: tracker.acknowledged)
    elif scenario == "onset_no_terminal":
        await _eventually(lambda: tracker.acknowledged and tracker.onset_seen)
    elif scenario == "onset_no_response":
        await _eventually(lambda: tracker.onset_seen)
    deadline.set()

    with pytest.raises(ICLightGroupError) as raised:
        await task

    error = raised.value
    assert error.phase == phase
    assert error.dispatch_started is True
    assert error.response_received is response_received
    assert error.acknowledged is acknowledged
    assert error.onset_seen is onset_seen
    assert connection.observers == []
    assert len([call for call in connection.calls if call.command == "SetParamList"]) == 1
    assert all(
        call.kwargs["objectList"][0]["params"] == {"SYNC": "ON"}
        for call in connection.calls
        if call.command == "SetParamList"
    )


@pytest.mark.asyncio
async def test_already_expired_absolute_deadline_beats_ready_action_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller(frames=[])
    _fast_lifecycle(monkeypatch)

    async def complete_after_expired_start(
        conn: ScriptedConnection,
        before: Any,
        after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        before(conn._sequence, asyncio.get_running_loop().time() - 61.0)
        after(conn._sequence)
        for frame in action_frames("OFF"):
            conn.emit(frame)
        return conn.action_response

    connection.scripts[("SetParamList", 1)] = complete_after_expired_start

    with pytest.raises(ICLightGroupError) as raised:
        await controller.run_light_group_sync("GROUP")

    assert raised.value.phase == "acknowledgement"
    assert raised.value.dispatch_started is True
    assert len([call for call in connection.calls if call.command == "SetParamList"]) == 1
    assert [call.command for call in connection.calls].count("GetParamList") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["non_200", "missing_message_id", "empty_message_id", "command_error"]
)
async def test_explicit_action_response_errors_are_acknowledgement_failures(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    controller, connection = make_controller(frames=[])
    _fast_lifecycle(monkeypatch)
    if kind == "non_200":
        connection.action_response = {"messageID": "4", "response": "500"}
    elif kind == "missing_message_id":
        connection.action_response = {"response": "200"}
    elif kind == "empty_message_id":
        connection.action_response = {"messageID": "", "response": "200"}
    else:
        connection.action_error = ICCommandError("500")

    with pytest.raises(ICLightGroupError) as raised:
        await controller.run_light_group_sync("GROUP")

    assert raised.value.phase == "acknowledgement"
    assert raised.value.response_received is True
    assert raised.value.acknowledged is False
    assert raised.value.onset_seen is False
    assert len([call for call in connection.calls if call.command == "SetParamList"]) == 1


@pytest.mark.asyncio
async def test_action_timeout_before_response_has_uncertain_delivery_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller(frames=[])
    _fast_lifecycle(monkeypatch)
    connection.action_error = TimeoutError("response timeout")

    with pytest.raises(ICLightGroupError) as raised:
        await controller.run_light_group_sync("GROUP")

    assert raised.value.phase == "acknowledgement"
    assert raised.value.response_received is False
    assert raised.value.acknowledged is False
    assert raised.value.onset_seen is False


@pytest.mark.asyncio
async def test_invariant_between_before_and_after_write_fails_post_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller(frames=[])
    _fast_lifecycle(monkeypatch)
    connection.between_write_frames = [
        {"command": "NotifyList", "objectList": [_entry("AUX", STATUS="ON")]}
    ]

    with pytest.raises(ICLightGroupError) as raised:
        await controller.run_light_group_sync("GROUP")

    assert raised.value.phase == "acknowledgement"
    assert raised.value.dispatch_started is True
    assert raised.value.response_received is False


@pytest.mark.asyncio
async def test_pre_watermark_sync_on_needs_a_fresh_post_watermark_onset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller(frames=[])
    monkeypatch.setattr(light_group, "SUBSCRIPTION_SETTLE_SECONDS", 0)
    deadline = _deadline_barrier(monkeypatch)
    captured = _capture_tracker(monkeypatch)
    connection.between_write_frames = [
        {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]}
    ]
    connection.action_frames = [
        {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="OFF")]}
    ]
    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await _eventually(lambda: bool(captured) and captured[0].acknowledged)
    assert captured[0].onset_seen is False
    deadline.set()

    with pytest.raises(ICLightGroupError) as raised:
        await task

    assert raised.value.phase == "onset"
    assert raised.value.acknowledged is True
    assert raised.value.onset_seen is False


@pytest.mark.asyncio
async def test_post_terminal_invariant_failure_is_observation_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller()
    monkeypatch.setattr(light_group, "SUBSCRIPTION_SETTLE_SECONDS", 0)
    captured = _capture_tracker(monkeypatch)
    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await _eventually(
        lambda: bool(captured) and captured[0].acknowledged and captured[0].terminal_event.is_set()
    )
    connection.emit({"command": "NotifyList", "objectList": [_entry("AUX", STATUS="ON")]})

    with pytest.raises(ICLightGroupError) as raised:
        await task

    assert raised.value.phase == "observation"
    assert raised.value.response_received is True
    assert raised.value.acknowledged is True
    assert raised.value.onset_seen is True
    assert [call.command for call in connection.calls].count("GetParamList") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ["target_status", "unrelated_status", "group_flag", "row_use", "system_service", "subtype"],
)
async def test_final_projection_mismatch_has_final_phase_metadata(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    final_raw = final_projection("OFF")
    by_name = {entry["objnam"]: entry for entry in final_raw["objectList"]}
    if case == "target_status":
        by_name["CHILD_A"]["params"]["STATUS"] = "OFF"
    elif case == "unrelated_status":
        by_name["AUX"]["params"]["STATUS"] = "ON"
    elif case == "group_flag":
        by_name["OTHER_GROUP"]["params"]["SYNC"] = "ON"
    elif case == "row_use":
        by_name["ROW_A"]["params"]["USE"] = "REAL"
    elif case == "system_service":
        by_name["SYS"]["params"]["SERVICE"] = "MANUAL"
    elif case == "subtype":
        by_name["CHILD_A"]["params"]["SUBTYP"] = "INTELLI"
    controller = make_cached_controller()
    connection = ScriptedConnection(
        [make_projection("OFF"), make_projection("OFF"), final_raw],
        action_frames=action_frames("OFF"),
    )
    controller._connection = connection  # type: ignore[assignment]
    _fast_lifecycle(monkeypatch)

    with pytest.raises(ICLightGroupError) as raised:
        await controller.run_light_group_sync("GROUP")

    assert raised.value.phase == "final_projection"
    assert raised.value.response_received is True
    assert raised.value.acknowledged is True
    assert raised.value.onset_seen is True
    assert connection.observers == []


@pytest.mark.asyncio
async def test_unsafe_notification_during_final_read_wins_over_clean_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller()
    _fast_lifecycle(monkeypatch)
    connection.before_response_frames[("GetParamList", 3)] = [
        {"command": "NotifyList", "objectList": [_entry("AUX", STATUS="ON")]}
    ]

    with pytest.raises(ICLightGroupError) as raised:
        await controller.run_light_group_sync("GROUP")

    assert raised.value.phase == "final_projection"
    assert "AUX.STATUS" in str(raised.value.__cause__)
    assert connection.observers == []


@pytest.mark.asyncio
async def test_normalized_row_use_spellings_compare_across_all_three_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = make_projection("OFF")
    second = make_projection("OFF")
    final = final_projection("OFF")
    next(entry for entry in first["objectList"] if entry["objnam"] == "ROW_A")["params"].pop(
        "USE", None
    )
    next(entry for entry in second["objectList"] if entry["objnam"] == "ROW_A")["params"]["USE"] = (
        "USE"
    )
    next(entry for entry in final["objectList"] if entry["objnam"] == "ROW_A")["params"]["USE"] = (
        "00000"
    )
    controller = make_cached_controller()
    connection = ScriptedConnection([first, second, final], action_frames=action_frames("OFF"))
    controller._connection = connection  # type: ignore[assignment]
    _fast_lifecycle(monkeypatch)

    ack = await controller.run_light_group_sync("GROUP")

    assert ack is connection.action_response


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["tcp", "websocket"])
async def test_onset_may_lead_target_status_transitions(
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
) -> None:
    frames = [
        {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]},
        {"command": "NotifyList", "objectList": [_entry("CHILD_A", STATUS="ON")]},
        {"command": "NotifyList", "objectList": [_entry("GROUP", STATUS="ON")]},
        {"command": "NotifyList", "objectList": [_entry("CHILD_B", STATUS="ON")]},
        {"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="OFF")]},
    ]
    controller, connection = make_controller(frames=frames)
    controller._transport = transport
    _fast_lifecycle(monkeypatch)

    ack = await controller.run_light_group_sync("GROUP")

    assert ack is connection.action_response


@pytest.mark.asyncio
async def test_observation_wait_uses_exact_terminal_plus_sixty_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller()
    monkeypatch.setattr(light_group, "SUBSCRIPTION_SETTLE_SECONDS", 0)
    captured = _capture_tracker(monkeypatch)
    observation_started = asyncio.Event()
    release_observation = asyncio.Event()
    deadlines: list[float] = []

    async def wait_until(deadline: float) -> None:
        deadlines.append(deadline)
        observation_started.set()
        await release_observation.wait()

    monkeypatch.setattr(light_group, "_sleep_until", wait_until)
    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await observation_started.wait()

    assert captured[0].terminal_time is not None
    assert deadlines == [captured[0].terminal_time + 60.0]
    assert [call.command for call in connection.calls].count("GetParamList") == 2
    release_observation.set()
    ack = await task

    assert ack is connection.action_response
    assert [call.command for call in connection.calls].count("GetParamList") == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["first", "subscription", "second", "action"])
async def test_same_instance_reconnect_before_transport_is_pre_dispatch_and_close_wins(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    controller, connection = make_controller()
    _fast_lifecycle(monkeypatch)
    key = {
        "first": ("GetParamList", 1),
        "subscription": ("RequestParamList", 1),
        "second": ("GetParamList", 2),
        "action": ("SetParamList", 1),
    }[stage]
    captured_old: list[asyncio.Future[None]] = []

    async def reconnect_before_write(
        conn: ScriptedConnection,
        before: Any,
        _after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        captured_old.append(conn.reconnect_same_instance())
        conn.emit({"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]})
        if before is not None:
            before(conn._sequence, asyncio.get_running_loop().time())
        raise AssertionError("transport callback should reject the old generation")

    connection.scripts[key] = reconnect_before_write

    with pytest.raises(ICConnectionError) as raised:
        await controller.run_light_group_sync("GROUP")

    assert not isinstance(raised.value, ICLightGroupError)
    assert captured_old and captured_old[0].done() and not captured_old[0].cancelled()
    assert connection.capture_count == 1
    assert connection.observers == []
    if stage != "action":
        assert all(call.command != "SetParamList" for call in connection.calls)


@pytest.mark.asyncio
async def test_same_instance_reconnect_after_dispatch_rejects_new_generation_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller(frames=[])
    _fast_lifecycle(monkeypatch)
    captured_old: list[asyncio.Future[None]] = []

    async def reconnect_after_dispatch(
        conn: ScriptedConnection,
        before: Any,
        after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        before(conn._sequence, asyncio.get_running_loop().time())
        after(conn._sequence)
        captured_old.append(conn.reconnect_same_instance())
        conn.emit(
            {
                "command": "NotifyList",
                "objectList": [_entry("GROUP", SYNC="ON"), _entry("GROUP", SYNC="OFF")],
            }
        )
        await asyncio.Event().wait()
        raise AssertionError

    connection.scripts[("SetParamList", 1)] = reconnect_after_dispatch

    with pytest.raises(ICLightGroupError) as raised:
        await controller.run_light_group_sync("GROUP")

    assert raised.value.phase == "acknowledgement"
    assert raised.value.response_received is False
    assert raised.value.onset_seen is False
    assert captured_old[0].done() and not captured_old[0].cancelled()


@pytest.mark.asyncio
async def test_controller_connection_replacement_cannot_supply_action_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, old_connection = make_controller(frames=[])
    _fast_lifecycle(monkeypatch)
    replacement = ScriptedConnection(
        [make_projection("OFF"), make_projection("OFF"), final_projection("OFF")],
        action_frames=action_frames("OFF"),
    )
    old_future = old_connection.closed

    async def replace_after_dispatch(
        conn: ScriptedConnection,
        before: Any,
        after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        before(conn._sequence, asyncio.get_running_loop().time())
        after(conn._sequence)
        controller._connection = replacement  # type: ignore[assignment]
        conn.close_generation()
        replacement.emit(
            {
                "command": "NotifyList",
                "objectList": [_entry("GROUP", SYNC="ON"), _entry("GROUP", SYNC="OFF")],
            }
        )
        await asyncio.Event().wait()
        raise AssertionError

    old_connection.scripts[("SetParamList", 1)] = replace_after_dispatch

    with pytest.raises(ICLightGroupError) as raised:
        await controller.run_light_group_sync("GROUP")

    assert raised.value.phase == "acknowledgement"
    assert raised.value.onset_seen is False
    assert controller._connection is replacement
    assert replacement.observers == []
    assert old_future.done() and not old_future.cancelled()


@pytest.mark.asyncio
async def test_same_instance_reconnect_wakes_subscription_settle_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller()
    monkeypatch.setattr(light_group, "SUBSCRIPTION_SETTLE_SECONDS", 60.0)
    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await _eventually(
        lambda: [call.command for call in connection.calls] == ["GetParamList", "RequestParamList"]
    )
    old_future = connection.reconnect_same_instance()
    connection.emit({"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]})

    with pytest.raises(ICConnectionError, match="captured connection closed"):
        await task

    assert old_future.done() and not old_future.cancelled()
    assert connection.observers == []
    assert all(call.command != "SetParamList" for call in connection.calls)


@pytest.mark.asyncio
async def test_projected_change_wakes_subscription_settle_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller()
    monkeypatch.setattr(light_group, "SUBSCRIPTION_SETTLE_SECONDS", 60.0)
    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await _eventually(
        lambda: [call.command for call in connection.calls] == ["GetParamList", "RequestParamList"]
    )
    connection.emit({"command": "NotifyList", "objectList": [_entry("AUX", STATUS="ON")]})

    with pytest.raises(ICError, match="AUX.STATUS") as raised:
        await task

    assert not isinstance(raised.value, ICLightGroupError)
    assert connection.observers == []
    assert all(call.command != "SetParamList" for call in connection.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "expected_phase"),
    [
        ("first", None),
        ("subscription", None),
        ("second", None),
        ("action", "acknowledgement"),
        ("final", "final_projection"),
    ],
)
async def test_simultaneous_clean_response_and_close_always_chooses_close(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    expected_phase: str | None,
) -> None:
    controller, connection = make_controller()
    _fast_lifecycle(monkeypatch)
    key = {
        "first": ("GetParamList", 1),
        "subscription": ("RequestParamList", 1),
        "second": ("GetParamList", 2),
        "action": ("SetParamList", 1),
        "final": ("GetParamList", 3),
    }[stage]

    async def close_with_clean_response(
        conn: ScriptedConnection,
        before: Any,
        after: Any,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        if before is not None:
            before(conn._sequence, asyncio.get_running_loop().time())
        if after is not None:
            after(conn._sequence)
        if stage == "action":
            for frame in action_frames("OFF"):
                conn.emit(frame)
            response = conn.action_response
        elif stage == "subscription":
            response = conn._subscription_response(kwargs["objectList"])
        else:
            projection = final_projection("OFF") if stage == "final" else make_projection("OFF")
            response = {
                "messageID": str(conn._message_id),
                "response": "200",
                **projection,
            }
        conn.close_generation()
        return response

    connection.scripts[key] = close_with_clean_response

    if expected_phase is None:
        with pytest.raises(ICConnectionError, match="captured connection closed"):
            await controller.run_light_group_sync("GROUP")
    else:
        with pytest.raises(ICLightGroupError) as raised:
            await controller.run_light_group_sync("GROUP")
        assert raised.value.phase == expected_phase
        assert isinstance(raised.value.__cause__, ICConnectionError)

    assert connection.closed.done() and not connection.closed.cancelled()
    assert connection.observers == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("edge", "phase"),
    [("none", "onset"), ("onset", "terminal"), ("terminal", "observation")],
)
async def test_disconnect_wakes_onset_terminal_and_observation_waits(
    monkeypatch: pytest.MonkeyPatch,
    edge: str,
    phase: str,
) -> None:
    frames: list[dict[str, Any]] = []
    if edge in {"onset", "terminal"}:
        frames.append({"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="ON")]})
    if edge == "terminal":
        frames.append({"command": "NotifyList", "objectList": [_entry("GROUP", SYNC="OFF")]})
    controller, connection = make_controller(frames=frames)
    monkeypatch.setattr(light_group, "SUBSCRIPTION_SETTLE_SECONDS", 0)
    captured = _capture_tracker(monkeypatch)
    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await _eventually(
        lambda: (
            bool(captured)
            and captured[0].acknowledged
            and (edge == "none" or captured[0].onset_seen)
            and (edge != "terminal" or captured[0].terminal_event.is_set())
        )
    )
    old = connection.closed
    connection.close_generation()

    with pytest.raises(ICLightGroupError) as raised:
        await task

    assert raised.value.phase == phase
    assert old.done() and not old.cancelled()
    assert connection.observers == []


@pytest.mark.asyncio
async def test_disconnect_during_final_read_has_final_projection_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller()
    _fast_lifecycle(monkeypatch)
    final_started = asyncio.Event()

    async def block_final(
        _conn: ScriptedConnection,
        before: Any,
        _after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        before(connection._sequence, asyncio.get_running_loop().time())
        final_started.set()
        await asyncio.Event().wait()
        raise AssertionError

    connection.scripts[("GetParamList", 3)] = block_final
    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await final_started.wait()
    old = connection.closed
    connection.close_generation()

    with pytest.raises(ICLightGroupError) as raised:
        await task

    assert raised.value.phase == "final_projection"
    assert raised.value.acknowledged is True
    assert old.done() and not old.cancelled()


@pytest.mark.asyncio
async def test_close_beats_operation_error_and_tracker_failure_beats_operation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fast_lifecycle(monkeypatch)
    close_controller, close_connection = make_controller()

    async def close_and_raise(
        conn: ScriptedConnection,
        _before: Any,
        _after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        conn.close_generation()
        raise RuntimeError("operation error must lose")

    close_connection.scripts[("RequestParamList", 1)] = close_and_raise
    with pytest.raises(ICConnectionError, match="captured connection closed"):
        await close_controller.run_light_group_sync("GROUP")

    failure_controller, failure_connection = make_controller()

    async def fail_and_raise(
        conn: ScriptedConnection,
        _before: Any,
        _after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        conn.emit({"command": "NotifyList", "objectList": [_entry("AUX", STATUS="ON")]})
        raise RuntimeError("operation error must lose")

    failure_connection.scripts[("RequestParamList", 1)] = fail_and_raise
    with pytest.raises(ICError, match="AUX.STATUS"):
        await failure_controller.run_light_group_sync("GROUP")


@pytest.mark.asyncio
async def test_cancellation_cleans_children_and_observer_before_lifecycle_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller(frames=[])
    _fast_lifecycle(monkeypatch)
    entered = asyncio.Event()
    action_cancelled = asyncio.Event()

    async def stalled_action(
        conn: ScriptedConnection,
        before: Any,
        _after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        before(conn._sequence, asyncio.get_running_loop().time())
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            action_cancelled.set()

    connection.scripts[("SetParamList", 1)] = stalled_action
    original_lifecycle = controller._light_group_mutation_lifecycle
    exit_snapshots: list[tuple[int, bool, bool, bool, bool]] = []

    @contextlib.asynccontextmanager
    async def traced_lifecycle() -> Any:
        async with original_lifecycle() as lease:
            try:
                yield lease
            finally:
                exit_snapshots.append(
                    (
                        len(connection.observers),
                        action_cancelled.is_set(),
                        controller._light_group_mutation_pending,
                        controller._light_group_mutation_lease is lease,
                        controller._mutation_lock.locked(),
                    )
                )

    controller._light_group_mutation_lifecycle = traced_lifecycle  # type: ignore[method-assign]
    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await entered.wait()
    live_close = connection.closed
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert exit_snapshots == [(0, True, True, True, True)]
    assert connection.remove_count == 1
    assert controller._light_group_mutation_pending is False
    assert controller._light_group_mutation_lease is None
    assert controller._mutation_owner is None
    assert not controller._mutation_lock.locked()
    assert not live_close.cancelled()


@pytest.mark.asyncio
async def test_cancellation_before_dispatch_removes_observer_without_a_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller()
    _fast_lifecycle(monkeypatch)
    entered = asyncio.Event()

    async def blocked_first_read(
        _conn: ScriptedConnection,
        _before: Any,
        _after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError

    connection.scripts[("GetParamList", 1)] = blocked_first_read
    task = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await entered.wait()
    live_close = connection.closed
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert connection.observers == []
    assert connection.remove_count == 1
    assert all(call.command != "SetParamList" for call in connection.calls)
    assert controller._light_group_mutation_pending is False
    assert not live_close.cancelled()


@pytest.mark.asyncio
async def test_concurrent_sync_and_writer_fail_busy_while_read_remains_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, connection = make_controller(frames=[])
    _fast_lifecycle(monkeypatch)
    entered = asyncio.Event()

    async def stalled_action(
        conn: ScriptedConnection,
        before: Any,
        _after: Any,
        _kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        before(conn._sequence, asyncio.get_running_loop().time())
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError

    connection.scripts[("SetParamList", 1)] = stalled_action
    first = asyncio.create_task(controller.run_light_group_sync("GROUP"))
    await entered.wait()
    calls_before = len(connection.calls)

    with pytest.raises(ICError, match="in progress"):
        await controller.run_light_group_sync("GROUP")
    with pytest.raises(ICError, match="in progress"):
        await controller.request_changes("AUX", {"STATUS": "ON"})
    read_response = await controller.send_cmd("GetFoo")

    assert read_response["response"] == "200"
    assert len(connection.calls) == calls_before + 1
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert controller._light_group_mutation_pending is False
