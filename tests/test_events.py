"""Synthetic observations exercise safety rules, not panel compatibility."""

import pytest

from pyintellicenter import EventObservationReason, observe_fdr_event


@pytest.mark.parametrize(
    "status",
    [
        "inactive",
        "stopped",
        "cancelled",
        "OFF",
        "Running",
        " running",
        "",
        0,
        False,
        "EVENTSTATUS",
        {"status": "running"},
        ["running"],
    ],
)
def test_unvalidated_values_never_mean_inactive(status):
    state = observe_fdr_event({"EVENTSTATUS": status}, connected=True, fresh=True)
    assert state.active is None
    assert state.reason == EventObservationReason.UNKNOWN_STATUS
    assert state.raw_status == status


@pytest.mark.parametrize("params", [None, {}, {"EVENTID": "event"}, {"EVENTSTATUS": None}])
def test_absent_or_null_status_is_not_inactive(params):
    state = observe_fdr_event(params, connected=True, fresh=True)
    assert state.active is None
    assert state.reason == EventObservationReason.MISSING_STATUS
    assert state.raw == (params or {})


def test_changed_id_cannot_inherit_previous_status():
    running = observe_fdr_event(
        {"EVENTSTATUS": "running", "EVENTID": "one"}, connected=True, fresh=True
    )
    changed = observe_fdr_event({"EVENTID": "two"}, connected=True, fresh=True)
    assert running.active is True
    assert running.event_id == "one"
    assert changed.event_id == "two"
    assert changed.active is None
    assert "EVENTSTATUS" not in changed.raw


def test_disconnect_and_reconnect_require_explicit_fresh_observation():
    params = {"EVENTSTATUS": "running", "EVENTID": 0}
    assert observe_fdr_event(params).active is None
    disconnected = observe_fdr_event(params, fresh=True)
    assert disconnected.reason == EventObservationReason.UNAVAILABLE
    reconnected = observe_fdr_event(params, connected=True)
    assert reconnected.reason == EventObservationReason.STALE
    assert reconnected.raw == params
    assert reconnected.active is None
    fresh = observe_fdr_event(params, connected=True, fresh=True)
    assert fresh.active is True
    assert fresh.event_id == 0
    # Loss of visibility is neither inactivity nor cancellation.
    assert observe_fdr_event({}, connected=True, fresh=True).active is None


def test_raw_fields_are_isolated_and_firmware_fields_are_excluded():
    params = {"EVENTSTATUS": ["future"], "EVENTID": {"opaque": [1]}, "PROGRESS": "100"}
    state = observe_fdr_event(params, connected=True, fresh=True)
    params["EVENTSTATUS"].append("changed")
    params["EVENTID"]["opaque"].append(2)
    state.raw["EVENTID"]["opaque"].append(3)
    state.event_id["opaque"].append(4)
    state.raw_status.append("mutated")
    assert state.raw == {"EVENTSTATUS": ["future"], "EVENTID": {"opaque": [1]}}


def test_raw_distinguishes_absent_and_null_id():
    absent = observe_fdr_event({"EVENTSTATUS": "running"}, connected=True, fresh=True)
    null = observe_fdr_event(
        {"EVENTSTATUS": "running", "EVENTID": None}, connected=True, fresh=True
    )
    assert absent.active is null.active is True
    assert "EVENTID" not in absent.raw
    assert null.raw["EVENTID"] is None
