"""Offline regression review of prior observations and incomplete evidence."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pyintellicenter import LightGroupCapabilityReason as Reason
from pyintellicenter.light_group_diagnostics import validate_light_group_capture

FIXTURE = Path(__file__).parent / "fixtures/light_group/sync-tcp-off.json"
FAILURES = json.loads((FIXTURE.parent / "prior-failures.json").read_text())


@pytest.fixture
def capture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


@pytest.mark.parametrize(
    ("transport", "prestate", "ack_at", "onset_at", "terminal_at"),
    [
        ("tcp", "OFF", 0.002145, 0.219557, 35.286805),
        ("tcp", "ON", 0.002399, 0.275896, 36.238773),
        ("websocket", "OFF", 0.004273, 0.852700, 35.852674),
        ("websocket", "ON", 0.010514, 0.765173, 35.773954),
    ],
)
def test_recorded_sync_contracts(
    capture: dict[str, Any],
    transport: str,
    prestate: str,
    ack_at: float,
    onset_at: float,
    terminal_at: float,
) -> None:
    capture["transport"] = transport
    capture["acknowledgement_at"] = ack_at
    capture["events"][0]["at"] = onset_at
    capture["events"][-1]["at"] = terminal_at
    if prestate == "ON":
        for snapshot in ("cached", "baseline", "settled"):
            for entry in capture[snapshot]["objectList"]:
                if entry["objnam"] in {"GROUP", "CHILD_A", "CHILD_B"}:
                    entry["params"]["STATUS"] = "ON"
        for response in capture["subscriptions"]:
            for entry in response["objectList"]:
                if entry["objnam"] in {"GROUP", "CHILD_A", "CHILD_B"}:
                    entry["params"]["STATUS"] = "ON"
        capture["events"] = [capture["events"][0], capture["events"][-1]]
    assert validate_light_group_capture(capture).accepted


@pytest.mark.parametrize("action", ["SET", "SWIM"])
@pytest.mark.parametrize("transport", ["tcp", "websocket"])
def test_even_clean_diagnostic_trace_cannot_enable_an_unvalidated_action(
    capture: dict[str, Any], action: str, transport: str
) -> None:
    capture["action"] = action
    capture["transport"] = transport
    capture["request"]["objectList"][0]["params"] = {action: "ON"}
    report = validate_light_group_capture(capture)
    assert not report.accepted
    assert not report.capability.supported
    assert report.errors == ()


@pytest.mark.parametrize(
    ("action", "transport"),
    [(case["action"], case["transport"]) for case in FAILURES["persisted_flags"]],
)
def test_prior_persisted_cross_group_flags_fail_review(
    capture: dict[str, Any], action: str, transport: str
) -> None:
    capture["action"] = action
    capture["transport"] = transport
    capture["request"]["objectList"][0]["params"] = {action: "ON"}
    capture["events"].pop()
    for entry in capture["final"]["objectList"]:
        if entry["objnam"] in {"GROUP", "OTHER_GROUP"}:
            entry["params"].update(SYNC="ON", SET="ON", SWIM="ON")
    report = validate_light_group_capture(capture)
    assert not report.accepted
    assert "Missing matching sender-side SYNC terminal edge" in report.errors
    assert any("flags" in error for error in report.errors)


def test_prior_tcp_swim_terminal_then_late_mixed_state_is_rejected(capture: dict[str, Any]) -> None:
    capture["action"] = "SWIM"
    capture["request"]["objectList"][0]["params"] = {"SWIM": "ON"}
    recorded = FAILURES["tcp_swim"]
    capture["acknowledgement_at"] = recorded["acknowledgement_at"]
    capture["events"][0]["at"] = recorded["onset_at"]
    capture["events"][-1]["at"] = recorded["terminal_at"]
    for sequence, marker in enumerate(recorded["child_off"], start=6):
        child, at = marker["role"], marker["at"]
        capture["events"].append(
            {
                "at": at,
                "sequence": sequence,
                "frame": {
                    "command": "NotifyList",
                    "objectList": [{"objnam": child, "params": {"STATUS": "OFF"}}],
                },
            }
        )
        for entry in capture["final"]["objectList"]:
            if entry["objnam"] == child:
                entry["params"]["STATUS"] = "OFF"
    report = validate_light_group_capture(capture)
    assert not report.accepted
    assert report.capability.reason == Reason.SWIM_LATE_MIXED_STATE
    assert "Color Sync target returned off after reaching on" in report.errors
    assert "Terminal edge exceeds the production Sync deadline" in report.errors
    assert "Color Sync final circuit projection mismatch" in report.errors


@pytest.mark.parametrize("source", ["observer", "ui"])
def test_client_dependent_swim_signals_cannot_supply_sender_completion(
    capture: dict[str, Any], source: str
) -> None:
    capture["notification_source"] = source
    for event in (capture["events"][0], capture["events"][-1]):
        params = event["frame"]["objectList"][0]["params"]
        params[FAILURES["client_signals"]["official_browser"]] = params.pop(
            FAILURES["client_signals"]["local_sender"]
        )
    report = validate_light_group_capture(capture)
    assert not report.accepted
    assert any("initiating-connection" in error for error in report.errors)
    assert "Missing positive sender-side post-watermark SYNC onset" in report.errors


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("events", [], "onset"),
        ("final_at", 90.0, "60-second"),
        ("write_watermark", 10, "onset"),
        ("connection_continuous", False, "continuous"),
        ("acknowledgement", {"messageID": "wrong", "response": "200"}, "correlated"),
        ("acknowledgement", {"messageID": "action-1", "response": "400"}, "correlated"),
        ("acknowledgement_at", 60.0, "deadline"),
        ("subscription_settle_seconds", 0.0, "settle"),
        ("subscriptions", [], "subscription"),
    ],
)
def test_incomplete_capture_never_passes(
    capture: dict[str, Any], field: str, value: Any, message: str
) -> None:
    capture[field] = value
    report = validate_light_group_capture(capture)
    assert not report.accepted
    assert any(message in error for error in report.errors)


@pytest.mark.parametrize(
    "params", [{"ACT": "SYNC"}, {"STATUS": "ON"}, {"SYNC": "ON", "SWIM": "ON"}]
)
def test_payload_requires_dedicated_single_action(
    capture: dict[str, Any], params: dict[str, str]
) -> None:
    capture["request"]["objectList"][0]["params"] = params
    assert any("one dedicated" in error for error in validate_light_group_capture(capture).errors)


@pytest.mark.parametrize("value", [-1, True, "1", float("nan"), float("inf")])
def test_invalid_clock_values_fail_closed(capture: dict[str, Any], value: Any) -> None:
    capture["events"][0]["at"] = value
    with pytest.raises(ValueError, match="finite nonnegative"):
        validate_light_group_capture(capture)


def test_reordered_enqueue_sequences_fail_closed(capture: dict[str, Any]) -> None:
    capture["events"][1]["sequence"] = 1
    with pytest.raises(ValueError, match="enqueue order"):
        validate_light_group_capture(capture)


def test_missing_fresh_inventory_is_not_treated_as_a_partial_read(capture: dict[str, Any]) -> None:
    capture["final"]["objectList"].pop(2)
    report = validate_light_group_capture(capture)
    assert not report.accepted
    assert any("topology" in error for error in report.errors)


def test_cli_accepts_only_supported_complete_capture(
    tmp_path: Path, capture: dict[str, Any]
) -> None:
    supported = subprocess.run(
        [sys.executable, "-m", "pyintellicenter.light_group_diagnostics", str(FIXTURE)],
        capture_output=True,
        text=True,
    )
    assert supported.returncode == 0, supported.stderr
    assert json.loads(supported.stdout)["accepted"] is True
    invalid = copy.deepcopy(capture)
    invalid["events"] = []
    invalid_path = tmp_path / "incomplete.json"
    invalid_path.write_text(json.dumps(invalid))
    rejected = subprocess.run(
        [sys.executable, "-m", "pyintellicenter.light_group_diagnostics", str(invalid_path)],
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 1
    assert json.loads(rejected.stdout)["accepted"] is False


@pytest.mark.parametrize("snapshot", ["baseline", "settled", "final"])
def test_rejected_snapshot_is_not_authoritative(capture: dict[str, Any], snapshot: str) -> None:
    capture[snapshot]["response"] = "400"
    report = validate_light_group_capture(capture)
    assert not report.accepted
    assert any("successful response" in error for error in report.errors)


def test_late_child_reversion_cannot_be_hidden_by_clean_final_read(capture: dict[str, Any]) -> None:
    capture["events"].append(
        {
            "at": 44.0,
            "sequence": 6,
            "frame": {
                "command": "NotifyList",
                "objectList": [{"objnam": "CHILD_A", "params": {"STATUS": "OFF"}}],
            },
        }
    )
    report = validate_light_group_capture(capture)
    assert not report.accepted
    assert "Color Sync target returned off after reaching on" in report.errors


def test_concurrent_group_action_during_observation_fails(capture: dict[str, Any]) -> None:
    capture["events"].append(
        {
            "at": 44.0,
            "sequence": 6,
            "frame": {
                "command": "NotifyList",
                "objectList": [{"objnam": "OTHER_GROUP", "params": {"SYNC": "ON"}}],
            },
        }
    )
    report = validate_light_group_capture(capture)
    assert not report.accepted
    assert any("invariant changed" in error for error in report.errors)


def test_notifications_before_acknowledgement_remain_eligible(capture: dict[str, Any]) -> None:
    capture["acknowledgement_at"] = 40.0
    assert validate_light_group_capture(capture).accepted


@pytest.mark.parametrize("field", ["schema_version", "action", "transport"])
def test_unknown_capture_identity_is_rejected(capture: dict[str, Any], field: str) -> None:
    capture[field] = "unvalidated"
    with pytest.raises(ValueError):
        validate_light_group_capture(capture)


def test_unknown_firmware_cannot_be_validated_offline(capture: dict[str, Any]) -> None:
    capture["cached"]["objectList"][0]["params"]["VER"] = "3.008"
    report = validate_light_group_capture(capture)
    assert not report.accepted
    assert report.capability.reason == Reason.UNSUPPORTED_FIRMWARE


def test_duplicate_cached_identity_is_rejected(capture: dict[str, Any]) -> None:
    capture["cached"]["objectList"].append(capture["cached"]["objectList"][0])
    with pytest.raises(ValueError, match="Duplicate cached"):
        validate_light_group_capture(capture)


def test_malformed_cli_input_returns_json_failure(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schema_version":1}')
    result = subprocess.run(
        [sys.executable, "-m", "pyintellicenter.light_group_diagnostics", str(malformed)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["accepted"] is False
    assert result.stderr == ""
