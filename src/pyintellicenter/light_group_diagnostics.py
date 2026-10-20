"""Offline review of sanitized light-group captures against the Sync contract.

This module never connects to a panel. Passing these checks does not validate a
new action, firmware, physical result, restoration, or the capture's provenance.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ._light_group import (
    SUBSCRIPTION_SETTLE_SECONDS,
    SYNC_ACTION_DEADLINE_SECONDS,
    SYNC_POST_TERMINAL_OBSERVATION_SECONDS,
    LightGroupSyncTracker,
    build_subscription_batches,
    build_topology,
    parse_projection,
    validate_final_projection,
    validate_subscription_response,
)
from .controller import ICModelController, ICSystemInfo
from .exceptions import ICError
from .light_group import LightGroupAction, LightGroupActionDecision
from .model import PoolModel

if TYPE_CHECKING:
    from .connection import TransportType


@dataclass(frozen=True)
class LightGroupCaptureReport:
    """Diagnostic results, never an authorization to expand action support."""

    capability: LightGroupActionDecision
    errors: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        """Return whether a supported action's capture passes the Sync checks."""
        return self.capability.supported and not self.errors


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a nonempty string")
    return value


def _time(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected finite nonnegative seconds")
    if not math.isfinite(value) or value < 0:
        raise ValueError("Expected finite nonnegative seconds")
    return float(value)


def _sequence(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Expected a nonnegative enqueue sequence")
    return int(value)


def _snapshot(value: Any) -> dict[str, Any]:
    response = _mapping(value)
    _text(response.get("messageID"))
    if response.get("response") != "200":
        raise ValueError("Authoritative snapshot must have a successful response")
    return response


def validate_light_group_capture(capture: dict[str, Any]) -> LightGroupCaptureReport:
    """Review a version-1 capture, reusing production Sync validators.

    All times are seconds from transport write initiation. Events must retain
    sender-side enqueue order and include the complete post-terminal window.
    Invalid schema raises ValueError; protocol/preflight failures are reported.
    Unsupported actions remain unsupported even if their diagnostic checks pass.
    """
    if type(capture.get("schema_version")) is not int or capture["schema_version"] != 1:
        raise ValueError("Unsupported capture schema_version")
    action = LightGroupAction(_text(capture.get("action")))
    group = _text(capture.get("group_objnam"))
    transport = _text(capture.get("transport"))
    if transport not in {"tcp", "websocket"}:
        raise ValueError("Unsupported capture transport")

    cached = _mapping(capture.get("cached"))
    model = PoolModel()
    cached_names: set[str] = set()
    for raw in _list(cached.get("objectList")):
        entry = _mapping(raw)
        name = _text(entry.get("objnam"))
        if name in cached_names:
            raise ValueError("Duplicate cached object")
        cached_names.add(name)
        params = _mapping(entry.get("params"))
        _text(params.get("OBJTYP"))
        model.add_object(name, params)
    controller = ICModelController("192.0.2.1", model, transport=cast("TransportType", transport))
    systems = model.get_by_type("SYSTEM")
    if len(systems) == 1:
        controller._system_info = ICSystemInfo(
            systems[0].objnam,
            {"VER": systems[0]["VER"], "PROPNAME": "", "SNAME": "", "MODE": ""},
        )
    decision = controller.get_light_group_capabilities(group).for_action(action)
    errors: list[str] = []
    try:
        topology = build_topology(controller, group)
        baseline = parse_projection(_snapshot(capture.get("baseline")), topology)
        tracker_time = 0.0
        tracker = LightGroupSyncTracker(topology, clock=lambda: tracker_time)
        tracker.set_prewrite_baseline(baseline)
        batches = build_subscription_batches(topology)
        responses = _list(capture.get("subscriptions"))
        if len(responses) != len(batches):
            raise ValueError("Missing or extra subscription initialization batch")
        for batch, response in zip(batches, responses, strict=True):
            validate_subscription_response(_mapping(response), batch, baseline, topology)
        settled = parse_projection(_snapshot(capture.get("settled")), topology)
        if settled != baseline:
            raise ValueError("Preflight mismatch after subscription settle")
        if _time(capture.get("subscription_settle_seconds")) < SUBSCRIPTION_SETTLE_SECONDS:
            raise ValueError("Subscription initialization did not settle for one second")
    except (ICError, ValueError) as error:
        return LightGroupCaptureReport(decision, (str(error),))

    request = _mapping(capture.get("request"))
    message_id = _text(request.get("messageID"))
    expected_request = {
        "command": "SetParamList",
        "messageID": message_id,
        "objectList": [{"objnam": group, "params": {action.value: "ON"}}],
    }
    if request != expected_request:
        errors.append("Request must select exactly one parent and one dedicated action flag")
    ack = _mapping(capture.get("acknowledgement"))
    ack_at = _time(capture.get("acknowledgement_at"))
    if ack.get("messageID") != message_id or ack.get("response") != "200":
        errors.append("Missing correlated 200 acknowledgement")
    if ack_at >= SYNC_ACTION_DEADLINE_SECONDS:
        errors.append("Acknowledgement exceeds the production Sync deadline")
    if capture.get("notification_source") != "sender":
        errors.append(
            "Completion requires initiating-connection notifications, not observer/UI state"
        )
    if capture.get("connection_continuous") is not True:
        errors.append("Capture does not establish continuous initiating-connection observation")
    watermark = _sequence(capture.get("write_watermark"))
    tracker.mark_before_write(0, 0.0)
    tracker.mark_after_write(watermark)
    previous_sequence = -1
    previous_time = 0.0
    onset_at: float | None = None
    for raw in _list(capture.get("events")):
        event = _mapping(raw)
        tracker_time = _time(event.get("at"))
        sequence = _sequence(event.get("sequence"))
        if tracker_time < previous_time or sequence <= previous_sequence:
            raise ValueError("Events must retain monotonic time and strict enqueue order")
        previous_time, previous_sequence = tracker_time, sequence
        frame = _mapping(event.get("frame"))
        if frame.get("command") != "NotifyList":
            raise ValueError("Action events must be raw NotifyList frames")
        tracker.observe(sequence, frame)
        if onset_at is None and tracker.onset_seen:
            onset_at = tracker_time
    if tracker.failure is not None:
        errors.append(str(tracker.failure))
    if onset_at is None:
        errors.append("Missing positive sender-side post-watermark SYNC onset")
    elif onset_at >= SYNC_ACTION_DEADLINE_SECONDS:
        errors.append("Onset exceeds the production Sync deadline")
    if tracker.terminal_time is None:
        errors.append("Missing matching sender-side SYNC terminal edge")
    elif tracker.terminal_time >= SYNC_ACTION_DEADLINE_SECONDS:
        errors.append("Terminal edge exceeds the production Sync deadline")
    final_at = _time(capture.get("final_at"))
    if final_at < max(previous_time, ack_at):
        raise ValueError("Final projection precedes captured events or acknowledgement")
    if (
        tracker.terminal_time is not None
        and final_at < tracker.terminal_time + SYNC_POST_TERMINAL_OBSERVATION_SECONDS
    ):
        errors.append("Missing full 60-second post-terminal observation window")
    try:
        final = parse_projection(_snapshot(capture.get("final")), topology)
        validate_final_projection(final, baseline, topology)
    except (ICError, ValueError) as error:
        errors.append(str(error))
    return LightGroupCaptureReport(decision, tuple(errors))


def main() -> int:
    """Print a JSON diagnostic report for a local file; perform no network I/O."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Sanitized version-1 JSON capture")
    args = parser.parse_args()
    try:
        capture = _mapping(json.loads(args.capture.read_text(encoding="utf-8")))
        report = validate_light_group_capture(capture)
    except (OSError, ValueError, ICError) as error:
        print(json.dumps({"accepted": False, "errors": [str(error)]}))
        return 1
    print(json.dumps({"accepted": report.accepted, **asdict(report)}, indent=2))
    return 0 if report.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
