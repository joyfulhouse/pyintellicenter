"""Conservative planning and offline evidence checks; no panel writes simulated."""

import copy
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyintellicenter import (
    GroupMemberSpec,
    GroupSpec,
    ICGroupConfigurationError,
    ICModelController,
    PoolModel,
    compare_group_readback,
)
from scripts.plan_group_configuration import report_evidence

FIXTURES = Path(__file__).parent / "fixtures" / "group_configuration"


@pytest.fixture(params=["light_edit", "feature_edit"])
def evidence(request):
    return json.loads((FIXTURES / f"{request.param}.json").read_text())


def load(evidence):
    model = PoolModel()
    model.add_objects(evidence["objects"])
    spec_data = evidence["spec"]
    spec = GroupSpec(
        **{key: value for key, value in spec_data.items() if key != "members"},
        members=tuple(GroupMemberSpec(**member) for member in spec_data["members"]),
    )
    return ICModelController("192.0.2.1", model), spec


def codes(plan):
    return {problem.code for problem in plan.diagnostics}


def test_static_client_preview_and_json_round_trip(evidence):
    """Compare to independently transcribed static builders, not a panel schema."""
    controller, spec = load(evidence)
    plan = controller.validate_group_edit("GROUP", spec)
    assert plan.valid
    assert plan.preview_request() == evidence["expected_request"]
    assert json.loads(json.dumps(plan.preview_request())) == evidence["expected_request"]
    assert controller.model["GROUP"].sname == "Original"
    assert [obj.objnam for obj in controller.get_circuit_groups()] == ["GROUP"]
    assert [row.objnam for row in controller.get_circuit_group_members("GROUP")] == [
        "ROW_A",
        "ROW_B",
    ]
    preview = plan.preview_request()
    preview["arguments"]["OBJLIST"].clear()
    assert plan.preview_request() == evidence["expected_request"]
    assert not controller.group_configuration_capability.can_apply


def test_immutable_input_and_plan(evidence):
    controller, spec = load(evidence)
    source = list(spec.members)
    copied = replace(spec, members=source)
    source.clear()
    assert copied.members == spec.members
    plan = controller.validate_group_edit("GROUP", copied)
    with pytest.raises(FrozenInstanceError):
        plan.spec.sname = "mutated"
    replaced_plan = replace(plan, spec=replace(spec, sname="Changed"))
    assert not replaced_plan.valid
    with pytest.raises(ICGroupConfigurationError, match="Invalid"):
        replaced_plan.preview_request()
    assert compare_group_readback(replaced_plan, controller.model)[0].code == "unvalidated_plan"
    with pytest.raises(TypeError):
        GroupSpec(**{**evidence["spec"], "arbitrary_panel_parameter": "ON"})
    with pytest.raises(TypeError):
        GroupMemberSpec(circuit="CHILD_A", position=2)
    with pytest.raises(TypeError):
        replace(spec, time_minutes=True)
    with pytest.raises(TypeError):
        replace(spec, members=({"circuit": "CHILD_A"},))


@pytest.mark.parametrize("target", ["ROW_A", "CHILD_A", "ABSENT", "GROUP OTHER", "00000", ""])
def test_wrong_or_missing_parent(evidence, target):
    controller, spec = load(evidence)
    plan = controller.validate_group_edit(target, spec)
    assert not plan.valid
    with pytest.raises(ICGroupConfigurationError, match="Invalid"):
        plan.preview_request()


@pytest.mark.parametrize("circuit", ["MISSING", "CHILD_A OTHER", "00000", "", "GROUP", "ROW_A"])
def test_unresolved_or_unsupported_members(evidence, circuit):
    controller, spec = load(evidence)
    member = replace(spec.members[0], circuit=circuit)
    assert not controller.validate_group_edit("GROUP", replace(spec, members=(member,))).valid


def test_duplicate_empty_invalid_name_and_timer(evidence):
    controller, spec = load(evidence)
    assert "duplicate_member" in codes(
        controller.validate_group_edit("GROUP", replace(spec, members=(spec.members[0],) * 2))
    )
    assert "empty_members" in codes(
        controller.validate_group_edit("GROUP", replace(spec, members=()))
    )
    for name in (" ", "line\nbreak"):
        assert "invalid_name" in codes(
            controller.validate_group_edit("GROUP", replace(spec, sname=name))
        )
    for timer in (-1, 0, 1440, 1441):
        assert "unsupported_timer" in codes(
            controller.validate_group_edit("GROUP", replace(spec, time_minutes=timer))
        )
    assert "unsupported_subtype" in codes(
        controller.validate_group_edit("GROUP", replace(spec, subtype="UNKNOWN"))
    )


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("CIRCUIT", "MISSING", "invalid_row_reference"),
        ("CIRCUIT", ["CHILD_A"], "invalid_row_reference"),
        ("CIRCUIT", "CHILD_B", "duplicate_member"),
        ("LISTORD", "bad", "invalid_order"),
        ("LISTORD", "2", "invalid_order"),
        ("LISTORD", True, "invalid_order"),
    ],
)
def test_incomplete_existing_rows_are_not_silently_dropped(evidence, field, value, expected):
    controller, spec = load(evidence)
    controller.model.add_object("ROW_A", {field: value})
    assert expected in codes(controller.validate_group_edit("GROUP", spec))


def test_incomplete_parent_and_missing_rows(evidence):
    controller, spec = load(evidence)
    controller.model.add_object("GROUP", {"TIME": None})
    controller.model.remove_object("ROW_A")
    controller.model.remove_object("ROW_B")
    assert "incomplete_topology" in codes(controller.validate_group_edit("GROUP", spec))


def test_action_schema_and_body_constraints(evidence):
    controller, spec = load(evidence)
    action = "ON" if spec.subtype == "LITSHO" else None
    changed = replace(spec.members[0], action=action)
    assert not controller.validate_group_edit("GROUP", replace(spec, members=(changed,))).valid
    controller.model.add_object("POOL", {"OBJTYP": "BODY", "SUBTYP": "POOL"})
    controller.model.add_object("SPA", {"OBJTYP": "BODY", "SUBTYP": "SPA"})
    controller.model.add_object("CHILD_A", {"BODY": "POOL"})
    controller.model.add_object("CHILD_B", {"BODY": "SPA"})
    assert "body_conflict" in codes(controller.validate_group_edit("GROUP", spec))
    controller.model.add_object("CHILD_A", {"BODY": "MISSING"})
    assert "invalid_body" in codes(controller.validate_group_edit("GROUP", spec))


def test_create_is_planned_without_guessing_membership_workflow(evidence):
    controller, spec = load(evidence)
    plan = controller.validate_group_edit(None, spec)
    assert plan.valid
    with pytest.raises(ICGroupConfigurationError, match="Create membership"):
        plan.preview_request()
    assert compare_group_readback(plan, controller.model)[0].code == "unknown_created_id"
    assert (
        compare_group_readback(plan, controller.model, created_group_id="MISSING")[0].code
        == "missing_parent"
    )


@pytest.mark.asyncio
async def test_writes_always_fail_before_io_even_with_ack_or_timeout(evidence):
    controller, spec = load(evidence)
    plan = controller.validate_group_edit("GROUP", spec)
    connection = AsyncMock()
    controller._connection = connection
    for outcome in ({"response": "200"}, TimeoutError("uncertain")):
        connection.send_request.side_effect = outcome if isinstance(outcome, Exception) else None
        connection.send_request.return_value = outcome
        with pytest.raises(ICGroupConfigurationError, match="unavailable"):
            await controller.apply_group_edit(plan)
        connection.send_request.assert_not_awaited()
    assert controller.model["GROUP"].sname == "Original"


def test_readback_detects_partial_application_and_does_not_mutate(evidence):
    controller, spec = load(evidence)
    plan = controller.validate_group_edit("GROUP", spec)
    assert compare_group_readback(plan, controller.model)
    controller.model.add_object(
        "GROUP", {"SNAME": spec.sname.strip(), "TIME": str(spec.time_minutes)}
    )
    problems = compare_group_readback(plan, controller.model)
    assert [problem.path for problem in problems] == ["members"]
    for index, member in enumerate(spec.members):
        row_id = "ROW_A" if member.circuit == "CHILD_A" else "ROW_B"
        params = {"LISTORD": str(index + 1)}
        if spec.subtype == "CIRCGRP":
            params["ACT"] = member.action
        controller.model.add_object(row_id, params)
    assert compare_group_readback(plan, controller.model) == ()
    original_parent = controller.model["GROUP"]
    create_plan = controller.validate_group_edit(None, spec)
    assert compare_group_readback(create_plan, controller.model, created_group_id="GROUP") == ()
    assert controller.model["GROUP"] is original_parent
    controller.model.remove_object("CHILD_A")
    assert compare_group_readback(plan, controller.model)
    assert not controller.validate_group_edit("GROUP", spec).valid


def test_offline_harness_reports_gates_and_rejects_unknown_writes(evidence):
    report = report_evidence(evidence)
    assert report["valid"]
    assert report["static_request_preview"] == evidence["expected_request"]
    assert not report["capability"]["can_apply"]
    readback = copy.deepcopy(evidence)
    readback["readback_objects"] = readback["objects"]
    assert report_evidence(readback)["readback_diagnostics"]
    with pytest.raises(ValueError, match="Unknown"):
        report_evidence({**evidence, "write": True})
    with pytest.raises(TypeError):
        report_evidence({**evidence, "spec": {**evidence["spec"], "BODY": "POOL"}})


@pytest.mark.parametrize("snapshot_key", ["objects", "readback_objects"])
@pytest.mark.parametrize(
    "bad_entry",
    [
        None,
        {},
        {"objnam": "ORPHAN", "params": {}},
        {"objnam": "ORPHAN", "params": {"OBJTYP": " "}},
        {"objnam": "00000", "params": {"OBJTYP": "CIRCUIT"}},
    ],
)
def test_offline_harness_rejects_incomplete_snapshots(evidence, snapshot_key, bad_entry):
    data = copy.deepcopy(evidence)
    data[snapshot_key] = [*data["objects"], bad_entry]
    with pytest.raises(ValueError, match=snapshot_key):
        report_evidence(data)


@pytest.mark.parametrize("snapshot_key", ["objects", "readback_objects"])
def test_offline_harness_rejects_duplicate_ids_instead_of_merging(evidence, snapshot_key):
    data = copy.deepcopy(evidence)
    duplicate = copy.deepcopy(data["objects"][0])
    duplicate["params"]["SNAME"] = "Contradictory snapshot"
    data[snapshot_key] = [*data["objects"], duplicate]
    with pytest.raises(ValueError, match="duplicates an object ID"):
        report_evidence(data)


@pytest.mark.parametrize("snapshot_key", ["objects", "readback_objects"])
def test_offline_harness_requires_snapshot_lists(evidence, snapshot_key):
    with pytest.raises(ValueError, match="full object list"):
        report_evidence({**evidence, snapshot_key: {}})


@pytest.mark.asyncio
async def test_reconnect_reuses_parent_identity_and_reconciles_rows(evidence):
    """Exercise the existing lifecycle; plans never create row entities or subscriptions."""
    controller, spec = load(evidence)
    parent = controller.model["GROUP"]
    events = []
    controller.subscribe(None, lambda ctrl, updates: events.append(dict(updates)))
    snapshot = copy.deepcopy(evidence["objects"])
    snapshot = [entry for entry in snapshot if entry["objnam"] != "ROW_B"]
    snapshot[0]["params"]["SNAME"] = "Panel rename"
    snapshot.append(
        {
            "objnam": "ROW_NEW",
            "params": {
                "OBJTYP": "CIRCGRP",
                "PARENT": "GROUP",
                "CIRCUIT": "CHILD_B",
                "LISTORD": "3",
                "ACT": "ON",
            },
        }
    )
    batches = []
    connection = AsyncMock()
    connection.connected = True
    connection.set_disconnect_callback = MagicMock()
    connection.add_notification_observer = MagicMock(return_value=MagicMock())
    connection.set_notification_callback = MagicMock()

    async def respond(command, **kwargs):
        if command == "GetParamList" and kwargs.get("condition"):
            return {
                "objectList": [
                    {
                        "objnam": "INCR",
                        "params": {
                            "PROPNAME": "Test",
                            "VER": "test",
                            "MODE": "ENGLISH",
                            "SNAME": "Test",
                        },
                    }
                ]
            }
        if command == "GetParamList":
            return {"objectList": snapshot}
        if command == "RequestParamList":
            batches.extend(entry["objnam"] for entry in kwargs["objectList"])
        return {"objectList": snapshot}

    connection.send_request.side_effect = respond
    with patch("pyintellicenter.controller.ICConnection", return_value=connection):
        await controller.start()
        await controller.start()
    assert controller.model["GROUP"] is parent
    assert parent.sname == "Panel rename"
    assert controller.model["ROW_B"] is None
    assert [obj.objnam for obj in controller.get_circuit_groups()] == ["GROUP"]
    assert "ROW_B" not in batches
    assert batches.count("GROUP") == 2
    assert batches.count("ROW_NEW") == 2
    assert sum(event.get("ROW_B", "absent") is None for event in events) == 1
    assert controller.validate_group_edit("GROUP", spec).valid
    snapshot[:] = [entry for entry in snapshot if entry["objnam"] != "GROUP"]
    with patch("pyintellicenter.controller.ICConnection", return_value=connection):
        await controller.start()
    assert controller.get_circuit_groups() == []
    assert "missing_parent" in codes(controller.validate_group_edit("GROUP", spec))
    await controller.stop()
