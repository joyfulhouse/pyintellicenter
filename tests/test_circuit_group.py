"""Tests for circuit-group parent and membership-row helpers."""

import pytest

from pyintellicenter import ICModelController, PoolModel


@pytest.fixture
def controller() -> ICModelController:
    """Create a controller with an empty model."""
    return ICModelController("192.0.2.1", PoolModel(), 6681)


def add_real_group(model: PoolModel) -> None:
    """Add a hardware-shaped light-group parent and membership rows."""
    model.add_object("GROUP", {"OBJTYP": "CIRCUIT", "SUBTYP": "LITSHO"})
    model.add_object(
        "ROW_B",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "CIRCUIT": "CHILD_B",
            "LISTORD": "2",
        },
    )
    model.add_object(
        "ROW_BAD",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "CIRCUIT": "MISSING",
            "LISTORD": "bad",
        },
    )
    model.add_object(
        "ROW_A",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "CIRCUIT": "CHILD_A",
            "LISTORD": "1",
        },
    )
    model.add_object("CHILD_A", {"OBJTYP": "CIRCUIT", "SUBTYP": "GLOW"})
    model.add_object("CHILD_B", {"OBJTYP": "CIRCUIT", "SUBTYP": "GLOW"})


def test_real_group_enumerates_parent_not_members(
    controller: ICModelController,
) -> None:
    add_real_group(controller.model)
    controller.model.add_object("PLAIN_PARENT", {"OBJTYP": "CIRCUIT", "SUBTYP": "CIRCGRP"})
    controller.model.add_object("ORPHAN", {"OBJTYP": "CIRCGRP", "CIRCUIT": "CHILD_A"})

    assert [obj.objnam for obj in controller.get_circuit_groups()] == [
        "GROUP",
        "PLAIN_PARENT",
    ]


def test_members_are_numeric_order_then_stable_malformed_tail(
    controller: ICModelController,
) -> None:
    add_real_group(controller.model)

    assert [obj.objnam for obj in controller.get_circuit_group_members("GROUP")] == [
        "ROW_A",
        "ROW_B",
        "ROW_BAD",
    ]


def test_duplicate_orders_and_malformed_orders_use_object_name_tiebreaker(
    controller: ICModelController,
) -> None:
    controller.model.add_object(
        "ROW_VALID_Z",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "CIRCUIT": "Z",
            "LISTORD": "1",
        },
    )
    controller.model.add_object(
        "ROW_VALID_A",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "CIRCUIT": "A",
            "LISTORD": 1,
        },
    )
    controller.model.add_object(
        "ROW_MALFORMED_Z",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "CIRCUIT": "Z",
            "LISTORD": "not-a-number",
        },
    )
    controller.model.add_object(
        "ROW_NEGATIVE",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "CIRCUIT": "NEGATIVE",
            "LISTORD": "-1",
        },
    )
    controller.model.add_object(
        "ROW_MISSING",
        {"OBJTYP": "CIRCGRP", "PARENT": "GROUP", "CIRCUIT": "MISSING"},
    )
    controller.model.add_object(
        "ROW_MALFORMED_A",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "CIRCUIT": "A",
            "LISTORD": "bad",
        },
    )

    assert [obj.objnam for obj in controller.get_circuit_group_members("GROUP")] == [
        "ROW_VALID_A",
        "ROW_VALID_Z",
        "ROW_MALFORMED_A",
        "ROW_MALFORMED_Z",
        "ROW_MISSING",
        "ROW_NEGATIVE",
    ]


def test_parent_and_real_row_resolve_ordered_sibling_children(
    controller: ICModelController,
) -> None:
    add_real_group(controller.model)

    assert [obj.objnam for obj in controller.get_circuits_in_group("GROUP")] == [
        "CHILD_A",
        "CHILD_B",
    ]
    assert [obj.objnam for obj in controller.get_circuits_in_group("ROW_B")] == [
        "CHILD_A",
        "CHILD_B",
    ]


def test_real_rows_skip_invalid_and_missing_child_references(
    controller: ICModelController,
) -> None:
    controller.model.add_object("GROUP", {"OBJTYP": "CIRCUIT", "SUBTYP": "LITSHO"})
    controller.model.add_object("CHILD", {"OBJTYP": "CIRCUIT", "SUBTYP": "GLOW"})
    references = {
        "ROW_MISSING_KEY": None,
        "ROW_NON_STRING": 7,
        "ROW_BLANK": "   ",
        "ROW_MULTIPLE": "CHILD OTHER",
        "ROW_UNKNOWN": "UNKNOWN",
        "ROW_VALID": "CHILD",
    }
    for order, (objnam, reference) in enumerate(references.items()):
        params: dict[str, object] = {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "LISTORD": str(order),
        }
        if objnam != "ROW_MISSING_KEY":
            params["CIRCUIT"] = reference
        controller.model.add_object(objnam, params)

    assert [obj.objnam for obj in controller.get_circuits_in_group("GROUP")] == ["CHILD"]


@pytest.mark.parametrize("parent", ["MISSING", "", None, 7])
def test_real_row_requires_valid_group_parent(
    controller: ICModelController, parent: object
) -> None:
    controller.model.add_object("CHILD", {"OBJTYP": "CIRCUIT", "SUBTYP": "GLOW"})
    controller.model.add_object(
        "ROW",
        {"OBJTYP": "CIRCGRP", "PARENT": parent, "CIRCUIT": "CHILD"},
    )

    assert controller.get_circuits_in_group("ROW") == []


@pytest.mark.parametrize(
    ("objtype", "subtype"),
    [("CIRCUIT", "GLOW"), ("SYSTEM", None), ("CIRCGRP", None)],
)
def test_row_rejects_wrong_parent_type_or_subtype(
    controller: ICModelController, objtype: str, subtype: str | None
) -> None:
    parent_params: dict[str, object] = {"OBJTYP": objtype}
    if subtype is not None:
        parent_params["SUBTYP"] = subtype
    controller.model.add_object("NOT_GROUP", parent_params)
    controller.model.add_object("CHILD", {"OBJTYP": "CIRCUIT", "SUBTYP": "GLOW"})
    controller.model.add_object(
        "ROW",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "NOT_GROUP",
            "CIRCUIT": "CHILD",
        },
    )

    assert controller.get_circuits_in_group("NOT_GROUP") == []
    assert controller.get_circuits_in_group("ROW") == []


def test_legacy_standalone_row_resolves_directly_but_is_never_enumerated(
    controller: ICModelController,
) -> None:
    controller.model.add_object("A", {"OBJTYP": "CIRCUIT", "SUBTYP": "GLOW"})
    controller.model.add_object("B", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT"})
    controller.model.add_object("LEGACY", {"OBJTYP": "CIRCGRP", "CIRCUIT": "A MISSING B"})

    assert [obj.objnam for obj in controller.get_circuits_in_group("LEGACY")] == [
        "A",
        "B",
    ]
    assert controller.get_circuit_groups() == []
    assert controller.get_color_light_groups() == []


def test_color_group_results_are_real_parents(
    controller: ICModelController,
) -> None:
    add_real_group(controller.model)

    assert controller.circuit_group_has_color_lights("GROUP") is True
    assert [obj.objnam for obj in controller.get_color_light_groups()] == ["GROUP"]


def test_group_with_only_non_color_lights_is_not_a_color_group(
    controller: ICModelController,
) -> None:
    controller.model.add_object("GROUP", {"OBJTYP": "CIRCUIT", "SUBTYP": "LITSHO"})
    controller.model.add_object("LIGHT", {"OBJTYP": "CIRCUIT", "SUBTYP": "LIGHT"})
    controller.model.add_object("DIMMER", {"OBJTYP": "CIRCUIT", "SUBTYP": "DIMMER"})
    controller.model.add_object(
        "ROW_LIGHT",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "CIRCUIT": "LIGHT",
            "LISTORD": "1",
        },
    )
    controller.model.add_object(
        "ROW_DIMMER",
        {
            "OBJTYP": "CIRCGRP",
            "PARENT": "GROUP",
            "CIRCUIT": "DIMMER",
            "LISTORD": "2",
        },
    )

    assert controller.circuit_group_has_color_lights("GROUP") is False
    assert controller.get_color_light_groups() == []
