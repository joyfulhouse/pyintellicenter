"""Evidence-bounded light-group Color Sync lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from .exceptions import (
    ICCommandError,
    ICConnectionError,
    ICError,
    ICLightGroupError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ._mixins.circuit_group import _CircuitGroupMixin


SUBSCRIPTION_SETTLE_SECONDS = 1.0
SYNC_ACTION_DEADLINE_SECONDS = 60.0
SYNC_POST_TERMINAL_OBSERVATION_SECONDS = 60.0
MAX_PREBASELINE_NOTIFICATIONS = 1000
SUPPORTED_FIRMWARE = "1.064"
SUPPORTED_CHILD_SUBTYPE = "GLOW"
SUPPORTED_CHILD_COUNT = 2
ACTION_FLAGS = ("SYNC", "SET", "SWIM")
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
RELEVANT_TYPES = frozenset({"SYSTEM", "CIRCUIT", "CIRCGRP"})
OPTIONAL_FIELDS = frozenset({("CIRCUIT", "PARENT"), ("CIRCUIT", "USE"), ("CIRCGRP", "USE")})


@dataclass(frozen=True)
class LightGroupTopology:
    """Immutable cached topology used to constrain every fresh projection."""

    system_objnam: str
    target_objnam: str
    target_rows: tuple[tuple[str, str, str, str], ...]
    target_children: tuple[str, str]
    circuit_objnams: tuple[str, ...]
    circuit_subtypes: tuple[tuple[str, str], ...]
    circuit_parents: tuple[tuple[str, str | None], ...]
    group_parent_objnams: tuple[str, ...]
    row_objnams: tuple[str, ...]
    row_topology: tuple[tuple[str, str, str, str], ...]
    inventory: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _SystemProjection:
    objnam: str
    objtype: str
    version: str
    service: str


@dataclass(frozen=True)
class _CircuitProjection:
    objnam: str
    objtype: str
    subtype: str
    parent: str | None
    status: str
    use: str | None


@dataclass(frozen=True)
class _GroupProjection:
    objnam: str
    sync: str
    set_value: str
    swim: str


@dataclass(frozen=True)
class _RowProjection:
    objnam: str
    objtype: str
    parent: str
    circuit: str
    listord: str
    use: str | None


@dataclass(frozen=True)
class LightGroupProjection:
    """Normalized immutable safety projection."""

    system: _SystemProjection
    circuits: tuple[_CircuitProjection, ...]
    groups: tuple[_GroupProjection, ...]
    rows: tuple[_RowProjection, ...]


def _normalize_optional(key: str, value: Any = None, *, present: bool = True) -> str | None:
    if not present or value is None or value == key or value == "00000":
        return None
    if not isinstance(value, str):
        raise ICError(f"Malformed optional {key} value")
    return value


def _real_value(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value or value == key or value == "00000":
        raise ICError(f"Missing or malformed mandatory {key}")
    return value


def _cached_optional(obj: Any, key: str) -> str | None:
    return _normalize_optional(key, obj[key], present=key in obj.attribute_keys)


def build_topology(controller: _CircuitGroupMixin, group_objnam: str) -> LightGroupTopology:
    """Build and validate the exact cached action topology without I/O."""
    system_info = controller._system_info
    if system_info is None or system_info.sw_version != SUPPORTED_FIRMWARE:
        raise ValueError("Color Sync requires exact cached firmware 1.064")

    model = controller._model
    target = model[group_objnam]
    if target is None or target.objtype != "CIRCUIT" or target.subtype != "LITSHO":
        raise ValueError("Color Sync target is not a CIRCUIT/LITSHO parent")

    rows = controller.get_circuit_group_members(group_objnam)
    if len(rows) != SUPPORTED_CHILD_COUNT:
        raise ValueError("Color Sync requires exactly two membership rows")

    target_rows: list[tuple[str, str, str, str]] = []
    children: list[str] = []
    for row in rows:
        parent = row["PARENT"]
        child_ref = row["CIRCUIT"]
        order = row["LISTORD"]
        if (
            row.objtype != "CIRCGRP"
            or parent != group_objnam
            or not isinstance(child_ref, str)
            or not child_ref
            or any(character.isspace() for character in child_ref)
            or not isinstance(order, (str, int))
            or order in {"LISTORD", "00000"}
        ):
            raise ValueError("Color Sync membership topology is malformed")
        try:
            if int(order) < 0:
                raise ValueError
        except (TypeError, ValueError) as err:
            raise ValueError("Color Sync membership order is malformed") from err
        child = model[child_ref]
        if child is None or child.objtype != "CIRCUIT" or child.subtype != SUPPORTED_CHILD_SUBTYPE:
            raise ValueError("Color Sync children must be exact CIRCUIT/GLOW objects")
        children.append(child_ref)
        target_rows.append((row.objnam, parent, child_ref, str(order)))

    if len(set(children)) != SUPPORTED_CHILD_COUNT:
        raise ValueError("Color Sync children must be distinct")

    systems = model.get_by_type("SYSTEM")
    if len(systems) != 1 or systems[0].objnam != system_info.objnam:
        raise ValueError("Color Sync cached system topology must contain exactly one system")

    circuits = sorted(
        (obj for obj in model if obj.objtype == "CIRCUIT"), key=lambda obj: obj.objnam
    )
    group_parents = tuple(obj.objnam for obj in circuits if obj.subtype in {"CIRCGRP", "LITSHO"})
    all_rows = sorted(model.get_by_type("CIRCGRP"), key=lambda obj: obj.objnam)
    row_topology: list[tuple[str, str, str, str]] = []
    for row in all_rows:
        parent = row["PARENT"]
        circuit = row["CIRCUIT"]
        order = row["LISTORD"]
        if not all(isinstance(value, str) and value for value in (parent, circuit)):
            raise ValueError("Color Sync cached membership topology is incomplete")
        if not isinstance(order, (str, int)):
            raise ValueError("Color Sync cached membership order is incomplete")
        row_topology.append((row.objnam, parent, circuit, str(order)))

    return LightGroupTopology(
        system_objnam=system_info.objnam,
        target_objnam=group_objnam,
        target_rows=tuple(target_rows),
        target_children=(children[0], children[1]),
        circuit_objnams=tuple(obj.objnam for obj in circuits),
        circuit_subtypes=tuple((obj.objnam, obj.subtype or "") for obj in circuits),
        circuit_parents=tuple((obj.objnam, _cached_optional(obj, "PARENT")) for obj in circuits),
        group_parent_objnams=group_parents,
        row_objnams=tuple(row.objnam for row in all_rows),
        row_topology=tuple(row_topology),
        inventory=tuple(sorted((obj.objnam, obj.objtype) for obj in model)),
    )


def build_projection_query() -> dict[str, Any]:
    """Return the fixed-size wildcard safety projection request."""
    from .controller import MAX_ATTRIBUTES_PER_QUERY

    if len(PROJECTION_KEYS) > MAX_ATTRIBUTES_PER_QUERY:
        raise ICError("Color Sync projection exceeds the protocol query limit")
    return {
        "condition": "",
        "objectList": [{"objnam": "INCR", "keys": list(PROJECTION_KEYS)}],
    }


def build_subscription_batches(topology: LightGroupTopology) -> list[list[dict[str, Any]]]:
    """Build deterministic exact-object subscription batches under the key limit."""
    from .controller import MAX_ATTRIBUTES_PER_QUERY

    entries: list[dict[str, Any]] = [
        {"objnam": topology.system_objnam, "keys": ["OBJTYP", "VER", "SERVICE"]}
    ]
    groups = set(topology.group_parent_objnams)
    for objnam in topology.circuit_objnams:
        keys = ["OBJTYP", "SUBTYP", "PARENT", "STATUS", "USE"]
        if objnam in groups:
            keys.extend(ACTION_FLAGS)
        entries.append({"objnam": objnam, "keys": keys})
    for objnam in topology.row_objnams:
        entries.append(
            {"objnam": objnam, "keys": ["OBJTYP", "PARENT", "CIRCUIT", "LISTORD", "USE"]}
        )

    batches: list[list[dict[str, Any]]] = []
    batch: list[dict[str, Any]] = []
    count = 0
    for entry in entries:
        size = len(entry["keys"])
        if size > MAX_ATTRIBUTES_PER_QUERY:
            raise ICError("Color Sync subscription entry exceeds the protocol query limit")
        if batch and count + size > MAX_ATTRIBUTES_PER_QUERY:
            batches.append(batch)
            batch = []
            count = 0
        batch.append(entry)
        count += size
    if batch:
        batches.append(batch)
    return batches


def _raw_entries(response: Any) -> dict[str, tuple[str, dict[str, Any]]]:
    if not isinstance(response, dict):
        raise ICError("Color Sync projection response is malformed")
    object_list = response.get("objectList")
    if not isinstance(object_list, list):
        raise ICError("Color Sync projection objectList is malformed")
    entries: dict[str, tuple[str, dict[str, Any]]] = {}
    for raw in object_list:
        if not isinstance(raw, dict):
            raise ICError("Color Sync projection entry is malformed")
        objnam = raw.get("objnam")
        params = raw.get("params")
        if not isinstance(objnam, str) or not objnam or not isinstance(params, dict):
            raise ICError("Color Sync projection identity is malformed")
        if objnam in entries:
            raise ICError("Color Sync projection contains a duplicate object")
        objtype = _real_value(params, "OBJTYP")
        entries[objnam] = (objtype, params)
    return entries


def parse_projection(
    response: dict[str, Any],
    topology: LightGroupTopology,
) -> LightGroupProjection:
    """Parse and normalize one complete authoritative wildcard projection."""
    entries = _raw_entries(response)
    expected_relevant = {
        topology.system_objnam,
        *topology.circuit_objnams,
        *topology.row_objnams,
    }
    actual_relevant = {name for name, (objtype, _) in entries.items() if objtype in RELEVANT_TYPES}
    if actual_relevant != expected_relevant:
        raise ICError("Color Sync fresh topology differs from the cached model")

    system_type, system_params = entries[topology.system_objnam]
    if system_type != "SYSTEM":
        raise ICError("Color Sync system type changed")
    system = _SystemProjection(
        topology.system_objnam,
        system_type,
        _real_value(system_params, "VER"),
        _real_value(system_params, "SERVICE"),
    )

    cached_subtypes = dict(topology.circuit_subtypes)
    cached_parents = dict(topology.circuit_parents)
    circuits: list[_CircuitProjection] = []
    for objnam in topology.circuit_objnams:
        objtype, params = entries[objnam]
        subtype = _real_value(params, "SUBTYP")
        parent = _normalize_optional("PARENT", params.get("PARENT"), present="PARENT" in params)
        if (
            objtype != "CIRCUIT"
            or subtype != cached_subtypes[objnam]
            or parent != cached_parents[objnam]
        ):
            raise ICError("Color Sync fresh circuit topology differs from the cache")
        circuits.append(
            _CircuitProjection(
                objnam,
                objtype,
                subtype,
                parent,
                _real_value(params, "STATUS"),
                _normalize_optional("USE", params.get("USE"), present="USE" in params),
            )
        )

    group_states: list[_GroupProjection] = []
    for objnam in topology.group_parent_objnams:
        params = entries[objnam][1]
        group_states.append(
            _GroupProjection(
                objnam,
                _real_value(params, "SYNC"),
                _real_value(params, "SET"),
                _real_value(params, "SWIM"),
            )
        )

    cached_rows = {row[0]: row for row in topology.row_topology}
    rows: list[_RowProjection] = []
    for objnam in topology.row_objnams:
        objtype, params = entries[objnam]
        parent = _real_value(params, "PARENT")
        circuit = _real_value(params, "CIRCUIT")
        listord = _real_value(params, "LISTORD")
        if objtype != "CIRCGRP" or (objnam, parent, circuit, listord) != cached_rows[objnam]:
            raise ICError("Color Sync fresh membership topology differs from the cache")
        rows.append(
            _RowProjection(
                objnam,
                objtype,
                parent,
                circuit,
                listord,
                _normalize_optional("USE", params.get("USE"), present="USE" in params),
            )
        )

    return LightGroupProjection(system, tuple(circuits), tuple(group_states), tuple(rows))


def validate_initial_projection(
    projection: LightGroupProjection,
    topology: LightGroupTopology,
) -> Literal["ON", "OFF"]:
    """Validate the uniform prestate and return it."""
    if projection.system.version != SUPPORTED_FIRMWARE or projection.system.service != "AUTO":
        raise ICError("Color Sync fresh firmware/service gate failed")
    if any(
        (group.sync, group.set_value, group.swim) != ("OFF", "OFF", "OFF")
        for group in projection.groups
    ):
        raise ICError("Color Sync requires every group action flag to be OFF")
    circuits = {item.objnam: item for item in projection.circuits}
    target_names = (topology.target_objnam, *topology.target_children)
    statuses = tuple(circuits[name].status for name in target_names)
    if statuses not in {("ON", "ON", "ON"), ("OFF", "OFF", "OFF")}:
        raise ICError("Color Sync requires a canonical uniform target prestate")
    return statuses[0]  # type: ignore[return-value]


def validate_final_projection(
    final: LightGroupProjection,
    baseline: LightGroupProjection,
    topology: LightGroupTopology,
) -> None:
    """Require the exact baseline invariants plus target completion state."""
    if final.system != baseline.system or final.rows != baseline.rows:
        raise ICError("Color Sync final projection changed system or membership topology")
    baseline_circuits = {item.objnam: item for item in baseline.circuits}
    target_names = {topology.target_objnam, *topology.target_children}
    for circuit in final.circuits:
        old = baseline_circuits.get(circuit.objnam)
        if old is None:
            raise ICError("Color Sync final circuit inventory changed")
        if (
            circuit.objtype != old.objtype
            or circuit.subtype != old.subtype
            or circuit.parent != old.parent
            or circuit.use != old.use
            or (circuit.objnam in target_names and circuit.status != "ON")
            or (circuit.objnam not in target_names and circuit.status != old.status)
        ):
            raise ICError("Color Sync final circuit projection mismatch")
    baseline_groups = {item.objnam: item for item in baseline.groups}
    for group in final.groups:
        old_group = baseline_groups.get(group.objnam)
        if old_group is None:
            raise ICError("Color Sync final group inventory changed")
        if group.objnam == topology.target_objnam:
            if (
                group.sync != "OFF"
                or group.set_value != old_group.set_value
                or group.swim != old_group.swim
            ):
                raise ICError("Color Sync target flags did not return to baseline")
        elif group != old_group:
            raise ICError("Color Sync unrelated group flags changed")


def _projection_values(projection: LightGroupProjection) -> dict[str, dict[str, str | None]]:
    values: dict[str, dict[str, str | None]] = {
        projection.system.objnam: {
            "OBJTYP": projection.system.objtype,
            "VER": projection.system.version,
            "SERVICE": projection.system.service,
        }
    }
    for circuit in projection.circuits:
        values[circuit.objnam] = {
            "OBJTYP": circuit.objtype,
            "SUBTYP": circuit.subtype,
            "PARENT": circuit.parent,
            "STATUS": circuit.status,
            "USE": circuit.use,
        }
    for group in projection.groups:
        values[group.objnam].update(
            {"SYNC": group.sync, "SET": group.set_value, "SWIM": group.swim}
        )
    for row in projection.rows:
        values[row.objnam] = {
            "OBJTYP": row.objtype,
            "PARENT": row.parent,
            "CIRCUIT": row.circuit,
            "LISTORD": row.listord,
            "USE": row.use,
        }
    return values


def validate_subscription_response(
    response: dict[str, Any],
    request: list[dict[str, Any]],
    baseline: LightGroupProjection,
    _topology: LightGroupTopology,
) -> None:
    """Validate exact initialization coverage and normalized baseline equality."""
    if (
        response.get("response") != "200"
        or not isinstance(response.get("messageID"), str)
        or not response["messageID"]
    ):
        raise ICError("Color Sync subscription was not acknowledged")
    object_list = response.get("objectList")
    if not isinstance(object_list, list) or not object_list:
        raise ICError("Color Sync subscription initialization is malformed")
    requested = {item["objnam"]: tuple(item["keys"]) for item in request}
    actual: dict[str, dict[str, Any]] = {}
    for entry in object_list:
        if not isinstance(entry, dict):
            raise ICError("Color Sync subscription entry is malformed")
        objnam = entry.get("objnam")
        params = entry.get("params")
        if not isinstance(objnam, str) or objnam in actual or not isinstance(params, dict):
            raise ICError("Color Sync subscription identity is malformed")
        if objnam not in requested or set(params) - set(requested[objnam]):
            raise ICError("Color Sync subscription contains unexpected coverage")
        actual[objnam] = params
    if set(actual) != set(requested):
        raise ICError("Color Sync subscription is missing an object")

    expected = _projection_values(baseline)
    for objnam, keys in requested.items():
        params = actual[objnam]
        objtype = expected[objnam]["OBJTYP"]
        for key in keys:
            optional = (objtype, key) in OPTIONAL_FIELDS
            if key not in params and not optional:
                raise ICError("Color Sync subscription is missing a mandatory key")
            if optional:
                value = _normalize_optional(key, params.get(key), present=key in params)
            else:
                value = _real_value(params, key)
            if value != expected[objnam][key]:
                raise ICError("Color Sync subscription initialization differs from baseline")


class LightGroupSyncTracker:
    """Edge-qualified monotonic action and invariant tracker."""

    def __init__(self, topology: LightGroupTopology) -> None:
        self.topology = topology
        self.failure_event = asyncio.Event()
        self.write_started = asyncio.Event()
        self.watermark_ready = asyncio.Event()
        self.onset_event = asyncio.Event()
        self.terminal_event = asyncio.Event()
        self.failure: ICError | None = None
        self.baseline: LightGroupProjection | None = None
        self.prebaseline: list[tuple[int, dict[str, Any]]] = []
        self.dynamic_types = dict(topology.inventory)
        self.pre_send_sequence: int | None = None
        self.watermark: int | None = None
        self.write_started_at: float | None = None
        self.action_deadline: float | None = None
        self.terminal_time: float | None = None
        self.response_received = False
        self.acknowledged = False
        self.initial_status: Literal["ON", "OFF"] | None = None
        self.turned_on: set[str] = set()

    @property
    def onset_seen(self) -> bool:
        return self.onset_event.is_set()

    def _record_failure(self, error: ICError) -> None:
        if self.failure is None:
            self.failure = error
            self.failure_event.set()

    def raise_if_failed(self) -> None:
        if self.failure is not None:
            raise self.failure

    def set_prewrite_baseline(self, projection: LightGroupProjection) -> None:
        self.baseline = projection
        self.initial_status = validate_initial_projection(projection, self.topology)
        if self.initial_status == "ON":
            self.turned_on.update((self.topology.target_objnam, *self.topology.target_children))
        buffered, self.prebaseline = self.prebaseline, []
        for sequence, frame in buffered:
            self._observe_frame(sequence, frame)

    def observe(self, sequence: int, frame: dict[str, Any]) -> None:
        if self.failure is not None:
            return
        if self.baseline is None:
            self._observe_frame(sequence, frame, compare_baseline=False)
            if self.failure is not None:
                return
            if len(self.prebaseline) >= MAX_PREBASELINE_NOTIFICATIONS:
                self._record_failure(
                    ICError("Color Sync pre-baseline notification buffer overflow")
                )
                return
            self.prebaseline.append((sequence, copy.deepcopy(frame)))
            return
        self._observe_frame(sequence, frame)

    def _observe_frame(
        self,
        sequence: int,
        frame: dict[str, Any],
        *,
        compare_baseline: bool = True,
    ) -> None:
        try:
            object_list = frame.get("objectList") if isinstance(frame, dict) else None
            if not isinstance(object_list, list):
                raise ICError("Malformed Color Sync notification objectList")
            for entry in object_list:
                self._observe_entry(sequence, entry, compare_baseline=compare_baseline)
        except ICError as err:
            self._record_failure(err)
        except (KeyError, TypeError, ValueError) as err:
            self._record_failure(ICError(f"Malformed Color Sync notification: {err}"))

    def _observe_entry(
        self,
        sequence: int,
        entry: Any,
        *,
        compare_baseline: bool,
    ) -> None:
        if not isinstance(entry, dict):
            raise ICError("Malformed Color Sync notification entry")
        objnam = entry.get("objnam")
        params = entry.get("params")
        if not isinstance(objnam, str) or not objnam or not isinstance(params, dict):
            raise ICError("Malformed Color Sync notification identity")

        known_type = self.dynamic_types.get(objnam)
        announced_type_present = "OBJTYP" in params
        announced_type = params.get("OBJTYP")
        if announced_type_present and (
            not isinstance(announced_type, str)
            or not announced_type
            or announced_type == "OBJTYP"
            or announced_type == "00000"
        ):
            raise ICError("Malformed Color Sync notification object type")
        if known_type is None:
            if announced_type in RELEVANT_TYPES or (
                not announced_type_present and bool(set(params) & set(PROJECTION_KEYS))
            ):
                raise ICError("Color Sync notification introduced ambiguous topology")
            if announced_type_present:
                assert isinstance(announced_type, str)
                self.dynamic_types[objnam] = announced_type
            return
        if known_type not in RELEVANT_TYPES:
            if announced_type in RELEVANT_TYPES:
                raise ICError("Color Sync notification changed object relevance")
            if announced_type_present:
                assert isinstance(announced_type, str)
                self.dynamic_types[objnam] = announced_type
            return
        if announced_type_present and announced_type != known_type:
            raise ICError("Color Sync notification changed object type")

        if compare_baseline:
            assert self.baseline is not None
            expected = _projection_values(self.baseline)[objnam]
            expected_keys = set(expected)
        elif known_type == "SYSTEM":
            expected = None
            expected_keys = {"OBJTYP", "VER", "SERVICE"}
        elif known_type == "CIRCUIT":
            expected = None
            expected_keys = {"OBJTYP", "SUBTYP", "PARENT", "STATUS", "USE"}
            if objnam in self.topology.group_parent_objnams:
                expected_keys.update(ACTION_FLAGS)
        else:
            expected = None
            expected_keys = {"OBJTYP", "PARENT", "CIRCUIT", "LISTORD", "USE"}
        target_names = {self.topology.target_objnam, *self.topology.target_children}
        for key, raw_value in params.items():
            if key not in expected_keys:
                continue
            optional = (known_type, key) in OPTIONAL_FIELDS
            if optional:
                value = _normalize_optional(key, raw_value)
            else:
                if (
                    not isinstance(raw_value, str)
                    or not raw_value
                    or raw_value == key
                    or raw_value == "00000"
                ):
                    raise ICError(f"Malformed mandatory notification {key}")
                value = raw_value

            if not compare_baseline:
                if key == "STATUS" and objnam in target_names and value not in {"ON", "OFF"}:
                    raise ICError("Color Sync target status is noncanonical")
                if (
                    key == "SYNC"
                    and objnam == self.topology.target_objnam
                    and value
                    not in {
                        "ON",
                        "OFF",
                    }
                ):
                    raise ICError("Color Sync target SYNC is noncanonical")
                continue

            if not self.write_started.is_set():
                assert expected is not None
                if value != expected[key]:
                    raise ICError(f"Color Sync invariant changed: {objnam}.{key}")
                continue

            if key == "STATUS" and objnam in target_names:
                self._observe_target_status(objnam, value)
                continue
            if key == "SYNC" and objnam == self.topology.target_objnam:
                self._observe_target_sync(sequence, value)
                continue
            assert expected is not None
            if value != expected[key]:
                raise ICError(f"Color Sync invariant changed: {objnam}.{key}")

    def _observe_target_status(self, objnam: str, value: str | None) -> None:
        if value not in {"ON", "OFF"}:
            raise ICError("Color Sync target status is noncanonical")
        if self.initial_status == "ON" and value == "OFF":
            raise ICError("Color Sync all-on target turned off")
        if value == "ON":
            self.turned_on.add(objnam)
        elif objnam in self.turned_on:
            raise ICError("Color Sync target returned off after reaching on")

    def _observe_target_sync(self, sequence: int, value: str | None) -> None:
        if value not in {"ON", "OFF"}:
            raise ICError("Color Sync target SYNC is noncanonical")
        if (
            not self.watermark_ready.is_set()
            or self.watermark is None
            or sequence <= self.watermark
        ):
            return
        if self.terminal_event.is_set():
            if value == "ON":
                raise ICError("Color Sync target SYNC re-entered after terminal")
            return
        if not self.onset_event.is_set():
            if value == "ON":
                self.onset_event.set()
            return
        if value == "OFF":
            self.terminal_time = asyncio.get_running_loop().time()
            self.terminal_event.set()

    def mark_before_write(self, sequence: int, started_at: float) -> None:
        self.raise_if_failed()
        self.pre_send_sequence = sequence
        self.write_started_at = started_at
        self.action_deadline = started_at + SYNC_ACTION_DEADLINE_SECONDS
        self.write_started.set()

    def mark_after_write(self, sequence: int) -> None:
        self.watermark = sequence
        self.watermark_ready.set()


async def _cancel_and_await(task: asyncio.Task[Any] | None) -> None:
    if task is None:
        return
    if not task.done():
        task.cancel()
    with contextlib.suppress(BaseException):
        await task


async def _wait_deadline(deadline: float) -> None:
    async with asyncio.timeout_at(deadline):
        await asyncio.Event().wait()


async def _sleep_until(deadline: float) -> None:
    delay = max(0.0, deadline - asyncio.get_running_loop().time())
    await asyncio.sleep(delay)


def _closed_error() -> ICConnectionError:
    return ICConnectionError("Color Sync captured connection closed")


def _phase_for_tracker(
    tracker: LightGroupSyncTracker,
    fallback: Literal["acknowledgement", "onset", "terminal", "observation", "final_projection"],
) -> Literal["acknowledgement", "onset", "terminal", "observation", "final_projection"]:
    if not tracker.response_received or not tracker.acknowledged:
        return "acknowledgement"
    if not tracker.onset_event.is_set():
        return "onset"
    if not tracker.terminal_event.is_set():
        return "terminal"
    return fallback


def _wrap_post_dispatch(
    tracker: LightGroupSyncTracker,
    error: Exception,
    phase: Literal["acknowledgement", "onset", "terminal", "observation", "final_projection"],
) -> ICLightGroupError:
    return ICLightGroupError(
        str(error),
        phase=_phase_for_tracker(tracker, phase),
        response_received=tracker.response_received,
        acknowledged=tracker.acknowledged,
        onset_seen=tracker.onset_seen,
    )


async def run_light_group_sync(
    controller: _CircuitGroupMixin,
    group_objnam: str,
) -> dict[str, Any]:
    """Run one verified, non-retried Color Sync lifecycle."""
    build_topology(controller, group_objnam)
    tracker: LightGroupSyncTracker | None = None
    remover: Callable[[], None] | None = None
    owned_tasks: set[asyncio.Task[Any]] = set()
    phase: Literal["acknowledgement", "onset", "terminal", "observation", "final_projection"] = (
        "acknowledgement"
    )

    async def cleanup_inside_lifecycle() -> None:
        if remover is not None:
            remover()
        tasks = tuple(owned_tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(BaseException):
                await task

    try:
        async with contextlib.AsyncExitStack() as stack:
            lease = await stack.enter_async_context(controller._light_group_mutation_lifecycle())
            stack.push_async_callback(cleanup_inside_lifecycle)
            topology = build_topology(controller, group_objnam)
            connection = controller._connection
            if connection is None or not connection.connected:
                raise ICConnectionError("Not connected")
            connection_closed = connection._capture_closed_future()
            projection_query = build_projection_query()
            subscription_batches = build_subscription_batches(topology)
            tracker = LightGroupSyncTracker(topology)
            failure_task = asyncio.create_task(tracker.failure_event.wait())
            owned_tasks.add(failure_task)

            def observer(sequence: int, frame: dict[str, Any]) -> None:
                if connection_closed.done():
                    tracker._record_failure(_closed_error())
                    return
                tracker.observe(sequence, frame)

            remover = connection.add_notification_observer(observer)

            def closed_before_send(_sequence: int, _started_at: float) -> None:
                if connection_closed.done():
                    raise _closed_error()

            async def guarded(operation: Coroutine[Any, Any, Any]) -> Any:
                task: asyncio.Task[Any] = asyncio.create_task(operation)
                owned_tasks.add(task)
                done, _ = await asyncio.wait(
                    {task, connection_closed, failure_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if connection_closed in done:
                    await _cancel_and_await(task)
                    raise _closed_error()
                if failure_task in done:
                    await _cancel_and_await(task)
                    tracker.raise_if_failed()
                try:
                    result = await task
                except BaseException as error:
                    if connection_closed.done():
                        raise _closed_error() from error
                    tracker.raise_if_failed()
                    raise
                if connection_closed.done():
                    raise _closed_error()
                tracker.raise_if_failed()
                return result

            async def request(
                command: str,
                extra: dict[str, Any],
                *,
                request_timeout: float | None = None,
                before: Callable[[int, float], None] | None = closed_before_send,
                after: Callable[[int], None] | None = None,
            ) -> dict[str, Any]:
                return await controller._send_cmd_on_connection_unlocked(
                    connection,
                    command,
                    extra,
                    _mutation_lease=lease,
                    request_timeout=request_timeout,
                    _before_write_callback=before,
                    _after_write_callback=after,
                )

            first_response = await guarded(request("GetParamList", projection_query))
            baseline = parse_projection(first_response, topology)
            tracker.set_prewrite_baseline(baseline)
            tracker.raise_if_failed()

            for batch in subscription_batches:
                response = await guarded(request("RequestParamList", {"objectList": batch}))
                validate_subscription_response(response, batch, baseline, topology)
                tracker.raise_if_failed()

            await guarded(asyncio.sleep(SUBSCRIPTION_SETTLE_SECONDS))
            second_response = await guarded(request("GetParamList", projection_query))
            second = parse_projection(second_response, topology)
            if second != baseline:
                raise ICError("Color Sync preflight mismatch after subscription settle")
            tracker.raise_if_failed()

            def mark_before(sequence: int, started_at: float) -> None:
                if connection_closed.done():
                    raise _closed_error()
                tracker.mark_before_write(sequence, started_at)

            action_task = asyncio.create_task(
                request(
                    "SetParamList",
                    {"objectList": [{"objnam": group_objnam, "params": {"SYNC": "ON"}}]},
                    request_timeout=SYNC_ACTION_DEADLINE_SECONDS,
                    before=mark_before,
                    after=tracker.mark_after_write,
                )
            )
            owned_tasks.add(action_task)
            write_waiter = asyncio.create_task(tracker.write_started.wait())
            owned_tasks.add(write_waiter)
            initial_wait_set: set[asyncio.Future[Any]] = {
                action_task,
                write_waiter,
                connection_closed,
                failure_task,
            }
            initial_done, _ = await asyncio.wait(
                initial_wait_set,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if connection_closed in initial_done:
                await _cancel_and_await(action_task)
                raise _closed_error()
            if failure_task in initial_done:
                await _cancel_and_await(action_task)
                tracker.raise_if_failed()
            if connection_closed.done():
                await _cancel_and_await(action_task)
                raise _closed_error()
            if tracker.failure is not None:
                await _cancel_and_await(action_task)
                tracker.raise_if_failed()
            if action_task in initial_done and not tracker.write_started.is_set():
                try:
                    await action_task
                except BaseException as error:
                    if connection_closed.done():
                        raise _closed_error() from error
                    tracker.raise_if_failed()
                    raise
                if connection_closed.done():
                    raise _closed_error()
                tracker.raise_if_failed()
                raise ICError("Color Sync action completed before transport dispatch")

            if tracker.action_deadline is None:
                raise ICError("Color Sync dispatch deadline was not initialized")
            if asyncio.get_running_loop().time() >= tracker.action_deadline:
                raise ICError("Color Sync action deadline expired")
            deadline_task = asyncio.create_task(_wait_deadline(tracker.action_deadline))
            watermark_waiter = asyncio.create_task(tracker.watermark_ready.wait())
            onset_waiter = asyncio.create_task(tracker.onset_event.wait())
            terminal_waiter = asyncio.create_task(tracker.terminal_event.wait())
            owned_tasks.update({deadline_task, watermark_waiter, onset_waiter, terminal_waiter})
            action_processed = False
            acknowledgement: dict[str, Any] | None = None
            phase = "acknowledgement"
            while not (
                tracker.acknowledged
                and tracker.onset_event.is_set()
                and tracker.terminal_event.is_set()
            ):
                wait_set: set[asyncio.Future[Any]] = {
                    connection_closed,
                    failure_task,
                    deadline_task,
                }
                if not action_processed:
                    wait_set.add(action_task)
                if not tracker.watermark_ready.is_set():
                    wait_set.add(watermark_waiter)
                if not tracker.onset_event.is_set():
                    wait_set.add(onset_waiter)
                if not tracker.terminal_event.is_set():
                    wait_set.add(terminal_waiter)
                action_done, _ = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)
                if connection_closed in action_done:
                    raise _closed_error()
                if failure_task in action_done:
                    tracker.raise_if_failed()
                if connection_closed.done():
                    raise _closed_error()
                tracker.raise_if_failed()
                if (
                    deadline_task in action_done
                    or asyncio.get_running_loop().time() >= tracker.action_deadline
                ):
                    with contextlib.suppress(Exception):
                        deadline_task.exception()
                    raise ICError("Color Sync action deadline expired")
                if action_task in action_done and not action_processed:
                    action_processed = True
                    try:
                        acknowledgement = await action_task
                    except ICCommandError as error:
                        tracker.response_received = True
                        if connection_closed.done():
                            raise _closed_error() from error
                        tracker.raise_if_failed()
                        raise
                    except BaseException as error:
                        if connection_closed.done():
                            raise _closed_error() from error
                        tracker.raise_if_failed()
                        raise
                    tracker.response_received = True
                    if connection_closed.done():
                        raise _closed_error()
                    tracker.raise_if_failed()
                    if (
                        acknowledgement.get("response") != "200"
                        or not isinstance(acknowledgement.get("messageID"), str)
                        or not acknowledgement["messageID"]
                    ):
                        raise ICError("Color Sync acknowledgement is malformed")
                    tracker.acknowledged = True
                if connection_closed.done():
                    raise _closed_error()
                tracker.raise_if_failed()
                if asyncio.get_running_loop().time() >= tracker.action_deadline:
                    raise ICError("Color Sync action deadline expired")
                phase = _phase_for_tracker(tracker, "terminal")

            if not action_processed or acknowledgement is None:
                raise ICError("Color Sync acknowledgement was not processed")

            phase = "observation"
            if tracker.terminal_time is None:
                raise ICError("Color Sync terminal time was not recorded")
            observation_deadline = tracker.terminal_time + SYNC_POST_TERMINAL_OBSERVATION_SECONDS
            await guarded(_sleep_until(observation_deadline))

            phase = "final_projection"
            final_response = await guarded(request("GetParamList", projection_query))
            final = parse_projection(final_response, topology)
            validate_final_projection(final, baseline, topology)
            tracker.raise_if_failed()
            remover()
            remover = None
            return acknowledgement
    except asyncio.CancelledError:
        raise
    except ICLightGroupError:
        raise
    except Exception as err:
        if tracker is not None and tracker.write_started.is_set():
            raise _wrap_post_dispatch(tracker, err, phase) from err
        raise
