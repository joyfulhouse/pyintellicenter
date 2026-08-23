"""Tests for PoolModel and PoolObject classes."""

import logging
from collections.abc import KeysView, Mapping
from typing import Any

import pytest

from pyintellicenter import (
    BODY_TYPE,
    CIRCUIT_TYPE,
    FEATR_ATTR,
    OBJTYP_ATTR,
    PUMP_TYPE,
    SNAME_ATTR,
    STATUS_ATTR,
    SUBTYP_ATTR,
    PoolModel,
    PoolObject,
)


class TestPoolObject:
    """Tests for PoolObject class."""

    def test_create_pool_object(self):
        """Test creating a PoolObject."""
        obj = PoolObject(
            "TEST01",
            {
                OBJTYP_ATTR: CIRCUIT_TYPE,
                SUBTYP_ATTR: "INTELLI",
                SNAME_ATTR: "Test Light",
                STATUS_ATTR: "OFF",
                "USE": "WHITER",
            },
        )

        assert obj.objnam == "TEST01"
        assert obj.objtype == CIRCUIT_TYPE
        assert obj.subtype == "INTELLI"
        assert obj.sname == "Test Light"
        assert obj.status == "OFF"
        assert obj["USE"] == "WHITER"

    def test_pool_object_is_a_light(self, pool_object_light: PoolObject):
        """Test is_a_light property for light subtypes."""
        assert pool_object_light.is_a_light is True
        assert pool_object_light.supports_color_effects is True

    def test_pool_object_not_a_light(self, pool_object_switch: PoolObject):
        """Test is_a_light property for non-light objects."""
        assert pool_object_switch.is_a_light is False
        assert pool_object_switch.supports_color_effects is False

    def test_pool_object_light_show(self):
        """Test is_a_light_show property."""
        show = PoolObject(
            "SHOW1",
            {
                OBJTYP_ATTR: CIRCUIT_TYPE,
                SUBTYP_ATTR: "LITSHO",
                SNAME_ATTR: "Party Show",
                STATUS_ATTR: "OFF",
            },
        )
        assert show.is_a_light_show is True

    def test_pool_object_is_featured(self, pool_object_switch: PoolObject):
        """Test is_featured property."""
        assert pool_object_switch.is_featured is True

    def test_pool_object_not_featured(self):
        """Test is_featured property for non-featured circuit."""
        obj = PoolObject(
            "CIRC02",
            {
                OBJTYP_ATTR: CIRCUIT_TYPE,
                SUBTYP_ATTR: "GENERIC",
                SNAME_ATTR: "Aux Circuit",
                STATUS_ATTR: "OFF",
                FEATR_ATTR: "OFF",
            },
        )
        assert obj.is_featured is False

    def test_pool_object_on_off_status_circuit(self, pool_object_light: PoolObject):
        """Test on_status and off_status for circuit objects."""
        assert pool_object_light.on_status == "ON"
        assert pool_object_light.off_status == "OFF"

    def test_pool_object_on_off_status_pump(self, pool_object_pump: PoolObject):
        """Test on_status and off_status for pump objects."""
        assert pool_object_pump.on_status == "10"
        assert pool_object_pump.off_status == "4"

    def test_pool_object_update_existing_attribute(self, pool_object_light: PoolObject):
        """Test updating an existing attribute."""
        changed = pool_object_light.update({STATUS_ATTR: "ON"})

        assert pool_object_light.status == "ON"
        assert STATUS_ATTR in changed
        assert changed[STATUS_ATTR] == "ON"

    def test_pool_object_update_new_attribute(self, pool_object_light: PoolObject):
        """Test adding a new attribute via update."""
        changed = pool_object_light.update({"NEW_ATTR": "value"})

        assert pool_object_light["NEW_ATTR"] == "value"
        assert "NEW_ATTR" in changed

    def test_pool_object_update_unchanged_value(self, pool_object_light: PoolObject):
        """Test updating with the same value returns no changes."""
        original_status = pool_object_light.status
        changed = pool_object_light.update({STATUS_ATTR: original_status})

        assert changed == {}

    def test_pool_object_update_multiple_attributes(self, pool_object_light: PoolObject):
        """Test updating multiple attributes at once."""
        changed = pool_object_light.update(
            {
                STATUS_ATTR: "ON",
                "USE": "PARTY",
                "NEW_FIELD": "test",
            }
        )

        assert len(changed) == 3
        assert pool_object_light.status == "ON"
        assert pool_object_light["USE"] == "PARTY"
        assert pool_object_light["NEW_FIELD"] == "test"

    def test_pool_object_attribute_keys_property(self, pool_object_light: PoolObject):
        """Test attribute_keys property returns keys view."""
        keys = pool_object_light.attribute_keys
        assert isinstance(keys, KeysView)
        assert SNAME_ATTR in keys
        assert STATUS_ATTR in keys

    def test_pool_object_properties_property(self, pool_object_light: PoolObject):
        """Test properties property returns a mapping of the attributes."""
        props = pool_object_light.properties
        assert isinstance(props, Mapping)
        assert SNAME_ATTR in props
        assert props[SNAME_ATTR] == "Pool Light"

    def test_pool_object_str_representation(self, pool_object_light: PoolObject):
        """Test string representation includes key info."""
        str_repr = str(pool_object_light)
        assert "LIGHT1" in str_repr
        assert CIRCUIT_TYPE in str_repr
        assert "INTELLI" in str_repr

    def test_pool_object_repr_representation(self, pool_object_light: PoolObject):
        """Test repr representation for debugging."""
        repr_str = repr(pool_object_light)
        assert "PoolObject" in repr_str
        assert "LIGHT1" in repr_str
        assert "CIRCUIT" in repr_str


class TestPoolModel:
    """Tests for PoolModel class."""

    def test_create_empty_pool_model(self):
        """Test creating an empty PoolModel."""
        model = PoolModel()
        assert model.num_objects == 0
        assert len(list(model.object_values)) == 0

    def test_pool_model_add_object(self):
        """Test adding a single object to the model."""
        model = PoolModel()
        obj = model.add_object(
            "LIGHT1",
            {
                OBJTYP_ATTR: CIRCUIT_TYPE,
                SUBTYP_ATTR: "INTELLI",
                SNAME_ATTR: "Pool Light",
                STATUS_ATTR: "OFF",
            },
        )

        assert obj is not None
        assert model.num_objects == 1
        assert model["LIGHT1"] == obj

    def test_pool_model_add_objects_batch(self, pool_model_data: list[dict[str, Any]]):
        """Test adding multiple objects at once."""
        model = PoolModel()
        model.add_objects(pool_model_data)

        assert model.num_objects == len(pool_model_data)

    def test_pool_model_getitem(self, pool_model: PoolModel):
        """Test accessing objects by objnam using bracket notation."""
        light = pool_model["LIGHT1"]
        assert light is not None
        assert light.objnam == "LIGHT1"
        assert light.objtype == CIRCUIT_TYPE

    def test_pool_model_get_by_type(self, pool_model: PoolModel):
        """Test filtering objects by type."""
        bodies = pool_model.get_by_type(BODY_TYPE)
        assert len(bodies) == 2
        assert all(obj.objtype == BODY_TYPE for obj in bodies)

    def test_pool_model_get_by_type_and_subtype(self, pool_model: PoolModel):
        """Test filtering objects by type and subtype."""
        spa = pool_model.get_by_type(BODY_TYPE, "SPA")
        assert len(spa) == 1
        assert spa[0].objnam == "SPA01"
        assert spa[0].subtype == "SPA"

    def test_pool_model_get_children(self, pool_model: PoolModel):
        """Test getting children of an object."""
        # Add a parent-child relationship
        pool_model.add_object(
            "CHILD1",
            {
                OBJTYP_ATTR: CIRCUIT_TYPE,
                SUBTYP_ATTR: "GENERIC",
                "PARENT": "POOL1",
                SNAME_ATTR: "Child Circuit",
            },
        )

        pool_body = pool_model["POOL1"]
        children = pool_model.get_children(pool_body)

        assert len(children) >= 1
        assert any(c.objnam == "CHILD1" for c in children)

    def test_pool_model_iteration(self, pool_model: PoolModel):
        """Test iterating over all objects in the model."""
        count = 0
        for obj in pool_model:
            assert isinstance(obj, PoolObject)
            count += 1

        assert count == pool_model.num_objects

    def test_pool_model_object_values(self, pool_model: PoolModel):
        """Test object_values property."""
        objects = list(pool_model.object_values)
        assert len(objects) == pool_model.num_objects
        assert all(isinstance(obj, PoolObject) for obj in objects)

    def test_pool_model_objects_dict(self, pool_model: PoolModel):
        """Test objects property returns a mapping keyed by objnam."""
        objects_dict = pool_model.objects
        assert isinstance(objects_dict, Mapping)
        assert "LIGHT1" in objects_dict
        assert objects_dict["LIGHT1"].objtype == CIRCUIT_TYPE

    def test_pool_model_process_updates(self, pool_model: PoolModel):
        """Test processing updates to multiple objects."""
        updates = [
            {
                "objnam": "LIGHT1",
                "params": {STATUS_ATTR: "ON"},
            },
            {
                "objnam": "PUMP1",
                "params": {STATUS_ATTR: "10", "RPM": "2500"},
            },
        ]

        changed = pool_model.process_updates(updates)

        assert "LIGHT1" in changed
        assert changed["LIGHT1"][STATUS_ATTR] == "ON"
        assert "PUMP1" in changed
        assert changed["PUMP1"]["RPM"] == "2500"

        assert pool_model["LIGHT1"].status == "ON"
        assert pool_model["PUMP1"]["RPM"] == "2500"

    def test_pool_model_process_updates_unchanged(self, pool_model: PoolModel):
        """Test processing updates with no actual changes."""
        original_status = pool_model["LIGHT1"].status
        updates = [
            {
                "objnam": "LIGHT1",
                "params": {STATUS_ATTR: original_status},
            },
        ]

        changed = pool_model.process_updates(updates)

        assert changed == {}

    def test_pool_model_process_updates_unknown_object(self, pool_model: PoolModel):
        """Test processing updates for non-existent object without OBJTYP.

        A NotifyList entry for an unknown objnam that lacks enough information
        to construct the object (no OBJTYP) is ignored safely.
        """
        updates = [
            {
                "objnam": "UNKNOWN",
                "params": {STATUS_ATTR: "ON"},
            },
        ]

        added: set[str] = set()
        changed = pool_model.process_updates(updates, added)

        assert changed == {}
        assert added == set()
        assert pool_model["UNKNOWN"] is None
        assert pool_model.num_objects == 4  # unchanged

    def test_pool_model_process_updates_adds_new_object(self, pool_model: PoolModel):
        """A NotifyList for a brand-new object (with OBJTYP) adds it to the model.

        Simulates a freshly-installed 2nd IntelliChem appearing via NotifyList
        without a reconnect (issue #42).
        """
        original_count = pool_model.num_objects
        updates = [
            {
                "objnam": "CHM02",
                "params": {
                    OBJTYP_ATTR: "CHEM",
                    SUBTYP_ATTR: "ICHEM",
                    SNAME_ATTR: "IntelliChem 2",
                    STATUS_ATTR: "ON",
                },
            },
        ]

        added: set[str] = set()
        changed = pool_model.process_updates(updates, added)

        # Object is now in the model.
        new_obj = pool_model["CHM02"]
        assert new_obj is not None
        assert new_obj.objtype == "CHEM"
        assert new_obj.subtype == "ICHEM"
        assert new_obj.sname == "IntelliChem 2"
        assert pool_model.num_objects == original_count + 1

        # It is surfaced as a change and reported as newly added.
        assert "CHM02" in changed
        assert changed["CHM02"][STATUS_ATTR] == "ON"
        assert changed["CHM02"][OBJTYP_ATTR] == "CHEM"
        assert changed["CHM02"][SUBTYP_ATTR] == "ICHEM"
        assert added == {"CHM02"}

    def test_pool_model_process_updates_new_object_without_added_set(self, pool_model: PoolModel):
        """Adding a new object works even when no added_objnams set is passed.

        The added_objnams parameter is optional and backward-compatible.
        """
        updates = [
            {
                "objnam": "CHM02",
                "params": {OBJTYP_ATTR: "CHEM", SUBTYP_ATTR: "ICHEM"},
            },
        ]

        changed = pool_model.process_updates(updates)

        assert pool_model["CHM02"] is not None
        assert "CHM02" in changed

    def test_pool_model_process_updates_new_object_untracked_type(self):
        """A new object whose type is not tracked is not added or surfaced."""
        model = PoolModel(attribute_map={CIRCUIT_TYPE: {STATUS_ATTR}})
        updates = [
            {
                "objnam": "PUMP9",
                "params": {OBJTYP_ATTR: PUMP_TYPE, STATUS_ATTR: "10"},
            },
        ]

        added: set[str] = set()
        changed = model.process_updates(updates, added)

        assert changed == {}
        assert added == set()
        assert model["PUMP9"] is None
        assert model.num_objects == 0

    def test_pool_model_process_updates_mixed_new_and_existing(self, pool_model: PoolModel):
        """A single NotifyList can update an existing object and add a new one."""
        updates = [
            {"objnam": "LIGHT1", "params": {STATUS_ATTR: "ON"}},
            {
                "objnam": "CHM02",
                "params": {OBJTYP_ATTR: "CHEM", SUBTYP_ATTR: "ICHEM"},
            },
        ]

        added: set[str] = set()
        changed = pool_model.process_updates(updates, added)

        assert pool_model["LIGHT1"].status == "ON"
        assert pool_model["CHM02"] is not None
        assert "LIGHT1" in changed
        assert "CHM02" in changed
        assert added == {"CHM02"}

    def test_pool_model_process_updates_malformed_entries_safe(self, pool_model: PoolModel):
        """Malformed NotifyList entries never crash and don't corrupt the model."""
        original_count = pool_model.num_objects
        # Deliberately malformed entries (wrong shape/type) to exercise the
        # protocol hot-path robustness. Typed as list[Any] because these
        # intentionally violate the ObjectEntry contract.
        updates: list[Any] = [
            {"params": {STATUS_ATTR: "ON"}},  # missing 'objnam'
            {"objnam": "LIGHT1"},  # missing 'params'
            "not-a-dict",  # wrong type entirely
            {"objnam": "NEWBAD", "params": "garbage"},  # params not a dict
            {"objnam": "LIGHT1", "params": {STATUS_ATTR: "ON"}},  # valid
        ]

        added: set[str] = set()
        # Must not raise.
        changed = pool_model.process_updates(updates, added)

        # The one valid entry still applied; model not corrupted.
        assert pool_model["LIGHT1"].status == "ON"
        assert "LIGHT1" in changed
        assert added == set()
        assert pool_model["NEWBAD"] is None
        assert pool_model.num_objects == original_count

    def test_pool_model_attributes_to_track(self, pool_model: PoolModel):
        """Test generating attribute tracking queries."""
        queries = pool_model.attributes_to_track()

        assert isinstance(queries, list)
        assert len(queries) > 0

        # Each query should have objnam and keys
        for query in queries:
            assert "objnam" in query
            assert "keys" in query
            assert isinstance(query["keys"], list)

    def test_pool_model_add_existing_object_updates(self, pool_model: PoolModel, pool_model_data):
        """Test adding an object that already exists updates it."""
        original_count = pool_model.num_objects

        # Add same object with different attributes
        obj = pool_model.add_object(
            "LIGHT1",
            {
                OBJTYP_ATTR: CIRCUIT_TYPE,
                SUBTYP_ATTR: "INTELLI",
                SNAME_ATTR: "Updated Light Name",
                STATUS_ATTR: "ON",
            },
        )

        # Should return existing object updated
        assert obj.objnam == "LIGHT1"
        assert obj.sname == "Updated Light Name"
        assert pool_model.num_objects == original_count  # Count unchanged

    def test_pool_model_ignore_unknown_types(self):
        """Test that objects with untracked types are not added."""
        # Create model with limited attribute map
        model = PoolModel(attribute_map={CIRCUIT_TYPE: {STATUS_ATTR}})

        # Try to add a PUMP (not in attribute map)
        obj = model.add_object(
            "PUMP1",
            {
                OBJTYP_ATTR: PUMP_TYPE,
                SUBTYP_ATTR: "VS",
                SNAME_ATTR: "Pool Pump",
                STATUS_ATTR: "10",
            },
        )

        assert obj is None
        assert model.num_objects == 0

    def test_pool_model_repr(self, pool_model: PoolModel):
        """Test repr representation for debugging."""
        repr_str = repr(pool_model)
        assert "PoolModel" in repr_str
        assert "num_objects" in repr_str

    def test_pool_model_skip_objects_without_objtyp(self):
        """Test that objects without OBJTYP attribute are skipped.

        Firmware 3.008+ returns objects like _FDR where all params have
        key==value (e.g., OBJTYP: "OBJTYP"). After pruning, these objects
        have empty params and should be gracefully skipped.

        See: https://github.com/joyfulhouse/pyintellicenter/issues/12
        """
        model = PoolModel()

        # Simulate the _FDR object after pruning (empty params)
        obj = model.add_object("_FDR", {})
        assert obj is None
        assert model.num_objects == 0

        # Also test with partial params missing OBJTYP
        obj2 = model.add_object("PARTIAL", {SNAME_ATTR: "Test", "PARENT": "ROOT"})
        assert obj2 is None
        assert model.num_objects == 0

        # Ensure valid objects still work
        obj3 = model.add_object(
            "VALID1",
            {
                OBJTYP_ATTR: CIRCUIT_TYPE,
                SNAME_ATTR: "Valid Circuit",
                STATUS_ATTR: "OFF",
            },
        )
        assert obj3 is not None
        assert model.num_objects == 1

    def test_pool_model_add_objects_batch_skips_malformed(self):
        """Test that batch add_objects skips malformed entries gracefully."""
        model = PoolModel()

        # Mix of valid and invalid objects (simulating firmware 3.008 response)
        objects = [
            {
                "objnam": "VALID1",
                "params": {
                    OBJTYP_ATTR: CIRCUIT_TYPE,
                    SNAME_ATTR: "Valid Circuit",
                    STATUS_ATTR: "OFF",
                },
            },
            {
                "objnam": "_FDR",
                "params": {},  # Pruned firmware definition object
            },
            {
                "objnam": "VALID2",
                "params": {
                    OBJTYP_ATTR: BODY_TYPE,
                    SUBTYP_ATTR: "POOL",
                    SNAME_ATTR: "Pool",
                },
            },
        ]

        model.add_objects(objects)

        # Should have added only the 2 valid objects
        assert model.num_objects == 2
        assert model["VALID1"] is not None
        assert model["_FDR"] is None
        assert model["VALID2"] is not None


class TestObjtypSubtypChangeTracking:
    """Regression tests for issue #55: false OBJTYP/SUBTYP change reports."""

    def test_update_with_identical_objtyp_subtyp_reports_no_change(self):
        """Re-sending the current OBJTYP/SUBTYP must not be reported as a change."""
        obj = PoolObject(
            "B1",
            {OBJTYP_ATTR: BODY_TYPE, SUBTYP_ATTR: "POOL", SNAME_ATTR: "Pool"},
        )

        changed = obj.update({OBJTYP_ATTR: BODY_TYPE, SUBTYP_ATTR: "POOL"})

        assert changed == {}

    def test_identical_snapshot_replay_produces_empty_change_set(
        self, pool_model: PoolModel, pool_model_data: list[dict[str, Any]]
    ):
        """Replaying the full snapshot (as on reconnect) yields no changes.

        ICModelController.start() replays the RequestParamList snapshot through
        process_updates on every connect/reconnect; identical data must not
        fire the update callback for the whole model.
        """
        changed = pool_model.process_updates(pool_model_data)

        assert changed == {}

        # A second replay is just as quiet.
        assert pool_model.process_updates(pool_model_data) == {}

    def test_real_subtyp_transition_reported_exactly_once(self):
        """A genuine SUBTYP change is applied and reported once, then quiet."""
        obj = PoolObject("C1", {OBJTYP_ATTR: CIRCUIT_TYPE, SUBTYP_ATTR: "GENERIC"})

        changed = obj.update({SUBTYP_ATTR: "INTELLI"})
        assert changed == {SUBTYP_ATTR: "INTELLI"}
        assert obj.subtype == "INTELLI"

        # Re-sending the same value reports nothing.
        assert obj.update({SUBTYP_ATTR: "INTELLI"}) == {}

    def test_real_objtyp_transition_reported_exactly_once(self):
        """A genuine OBJTYP change is applied and reported once, then quiet."""
        obj = PoolObject("X1", {OBJTYP_ATTR: CIRCUIT_TYPE})

        changed = obj.update({OBJTYP_ATTR: PUMP_TYPE})
        assert changed == {OBJTYP_ATTR: PUMP_TYPE}
        assert obj.objtype == PUMP_TYPE

        assert obj.update({OBJTYP_ATTR: PUMP_TYPE}) == {}

    def test_subtyp_clear_to_none_applies_and_reports(self):
        """Explicitly clearing SUBTYP to None is applied and reported."""
        obj = PoolObject("C1", {OBJTYP_ATTR: CIRCUIT_TYPE, SUBTYP_ATTR: "GENERIC"})

        changed = obj.update({SUBTYP_ATTR: None})

        assert changed == {SUBTYP_ATTR: None}
        assert obj.subtype is None

        # Clearing again is a no-op.
        assert obj.update({SUBTYP_ATTR: None}) == {}


class TestModelHardening:
    """Regression tests for issue #56: aliasing, __contains__, exposure, reconcile."""

    def test_same_object_list_feeds_two_models(self, pool_model_data: list[dict[str, Any]]):
        """Feeding the same objectList into two models populates both.

        PoolObject.__init__ used to pop OBJTYP/SUBTYP out of the caller's dict,
        leaving the second model silently empty.
        """
        model_a = PoolModel()
        model_b = PoolModel()

        model_a.add_objects(pool_model_data)
        model_b.add_objects(pool_model_data)

        assert model_a.num_objects == len(pool_model_data)
        assert model_b.num_objects == len(pool_model_data)
        assert model_b["LIGHT1"] is not None
        assert model_b["LIGHT1"].objtype == CIRCUIT_TYPE
        assert model_b["LIGHT1"].subtype == "INTELLI"

        # The caller's dicts are left intact.
        assert all(OBJTYP_ATTR in entry["params"] for entry in pool_model_data)

    def test_post_add_external_mutation_does_not_corrupt_model(self):
        """Mutating the params dict after add_object leaves the model untouched."""
        model = PoolModel()
        params = {
            OBJTYP_ATTR: CIRCUIT_TYPE,
            SUBTYP_ATTR: "INTELLI",
            SNAME_ATTR: "Pool Light",
            STATUS_ATTR: "OFF",
        }
        obj = model.add_object("LIGHT1", params)
        assert obj is not None

        params[STATUS_ATTR] = "ON"
        params[SNAME_ATTR] = "Hacked"
        params["EXTRA"] = "value"

        assert obj.status == "OFF"
        assert obj.sname == "Pool Light"
        assert obj["EXTRA"] is None

    def test_untracked_type_rejection_leaves_params_intact(self):
        """A rejected add_object must not strip OBJTYP from the caller's dict."""
        model = PoolModel(attribute_map={CIRCUIT_TYPE: {STATUS_ATTR}})
        params = {OBJTYP_ATTR: PUMP_TYPE, SUBTYP_ATTR: "VS", STATUS_ATTR: "10"}

        assert model.add_object("PUMP1", params) is None
        assert params == {OBJTYP_ATTR: PUMP_TYPE, SUBTYP_ATTR: "VS", STATUS_ATTR: "10"}

    def test_contains_by_objnam(self, pool_model: PoolModel):
        """The in operator is keyed by objnam."""
        assert "LIGHT1" in pool_model
        assert "PUMP1" in pool_model
        assert "NOPE" not in pool_model

    def test_pool_object_properties_are_read_only(self, pool_object_light: PoolObject):
        """PoolObject.properties cannot be mutated to bypass change tracking."""
        props = pool_object_light.properties

        with pytest.raises(TypeError):
            props[STATUS_ATTR] = "ON"

        assert pool_object_light.status == "OFF"

    def test_pool_model_objects_are_read_only(self, pool_model: PoolModel):
        """PoolModel.objects cannot be mutated to bypass the model API."""
        objects = pool_model.objects

        with pytest.raises(TypeError):
            del objects["LIGHT1"]

        assert "LIGHT1" in pool_model

    def test_remove_object(self, pool_model: PoolModel):
        """remove_object deletes by objnam and returns the removed object."""
        original_count = pool_model.num_objects

        removed = pool_model.remove_object("LIGHT1")

        assert removed is not None
        assert removed.objnam == "LIGHT1"
        assert "LIGHT1" not in pool_model
        assert pool_model["LIGHT1"] is None
        assert pool_model.num_objects == original_count - 1

        # Removing an unknown objnam is a safe no-op.
        assert pool_model.remove_object("LIGHT1") is None
        assert pool_model.remove_object("NOPE") is None

    def test_reconcile_prunes_ghosts_and_reports_removals(
        self, pool_model: PoolModel, pool_model_data: list[dict[str, Any]]
    ):
        """reconcile removes objects absent from an authoritative snapshot."""
        # Snapshot no longer contains PUMP1 (deleted at the panel).
        snapshot = [entry for entry in pool_model_data if entry["objnam"] != "PUMP1"]

        removed = pool_model.reconcile(snapshot)

        assert removed == ["PUMP1"]
        assert "PUMP1" not in pool_model
        assert pool_model["PUMP1"] is None
        assert pool_model.num_objects == len(snapshot)

        # Survivors are untouched.
        assert pool_model["LIGHT1"] is not None
        assert pool_model["POOL1"] is not None
        assert pool_model["SPA01"] is not None

    def test_reconcile_full_snapshot_removes_nothing(
        self, pool_model: PoolModel, pool_model_data: list[dict[str, Any]]
    ):
        """reconcile against a complete snapshot is a no-op."""
        original_count = pool_model.num_objects

        removed = pool_model.reconcile(pool_model_data)

        assert removed == []
        assert pool_model.num_objects == original_count

    def test_reconcile_ignores_malformed_entries(self, pool_model: PoolModel):
        """Malformed snapshot entries are skipped, not treated as removals."""
        snapshot: list[Any] = [
            {"params": {}},  # missing objnam
            "not-a-dict",  # wrong type entirely
            {"objnam": 42, "params": {}},  # objnam not a string
            *[{"objnam": objnam} for objnam in ("LIGHT1", "POOL1", "SPA01", "PUMP1")],
        ]

        removed = pool_model.reconcile(snapshot)

        assert removed == []
        assert pool_model.num_objects == 4

    def test_add_objects_skips_malformed_entries(self):
        """add_objects tolerates entries missing objnam/params."""
        model = PoolModel()
        objects: list[Any] = [
            {"params": {OBJTYP_ATTR: CIRCUIT_TYPE}},  # missing objnam
            {"objnam": "NOPARAMS"},  # missing params
            "not-a-dict",  # wrong type entirely
            {"objnam": "BADPARAMS", "params": "garbage"},  # params not a dict
            {
                "objnam": "VALID1",
                "params": {OBJTYP_ATTR: CIRCUIT_TYPE, SNAME_ATTR: "Valid"},
            },
        ]

        # Must not raise.
        model.add_objects(objects)

        assert model.num_objects == 1
        assert model["VALID1"] is not None
        assert model["BADPARAMS"] is None


class TestDeepIngestAndSnapshotObservability:
    """Regression tests for issue #77: shallow ingest copies, silent partial snapshots."""

    def test_nested_list_mutation_after_add_object_does_not_affect_model(self):
        """Mutating a nested list in the caller's params after add is isolated.

        dict(params) only copied the top level, so nested list values stayed
        aliased: appending to the caller's list rewrote model state and
        bypassed change tracking.
        """
        model = PoolModel()
        params: dict[str, Any] = {
            OBJTYP_ATTR: CIRCUIT_TYPE,
            SUBTYP_ATTR: "LITSHO",
            SNAME_ATTR: "Party Show",
            "USE": ["C1", "C2"],
        }
        obj = model.add_object("SHOW1", params)
        assert obj is not None

        params["USE"].append("HACKED")
        params["USE"][0] = "MUTATED"

        assert obj["USE"] == ["C1", "C2"]

    def test_nested_dict_mutation_after_add_object_does_not_affect_model(self):
        """Mutating a nested dict in the caller's params after add is isolated."""
        model = PoolModel()
        params: dict[str, Any] = {
            OBJTYP_ATTR: CIRCUIT_TYPE,
            SNAME_ATTR: "Circuit",
            "META": {"limits": {"min": "0", "max": "100"}},
        }
        obj = model.add_object("CIRC9", params)
        assert obj is not None

        params["META"]["limits"]["max"] = "9999"
        params["META"]["extra"] = "HACKED"

        assert obj["META"] == {"limits": {"min": "0", "max": "100"}}

    def test_nested_list_mutation_after_re_add_does_not_affect_model(self):
        """Re-adding an existing objnam is nested-mutation isolated too.

        add_object routes an existing object through PoolObject.update(),
        which assigns values directly — bypassing the constructor's deep
        copy. The update-through-add cold ingest path must deep-copy as
        well, or the model stays aliased to the caller's nested list.
        """
        model = PoolModel()
        first: dict[str, Any] = {
            OBJTYP_ATTR: CIRCUIT_TYPE,
            SUBTYP_ATTR: "LITSHO",
            "USE": ["C1"],
        }
        obj = model.add_object("SHOW1", first)
        assert obj is not None

        second: dict[str, Any] = {"USE": ["C1", "C2"]}
        re_added = model.add_object("SHOW1", second)
        assert re_added is obj

        second["USE"].append("HACKED")
        second["USE"][0] = "MUTATED"

        assert obj["USE"] == ["C1", "C2"]

    def test_nested_dict_mutation_after_re_add_via_add_objects_does_not_affect_model(self):
        """The batch path (add_objects) is isolated when updating existing objects."""
        model = PoolModel()
        model.add_object("CIRC9", {OBJTYP_ATTR: CIRCUIT_TYPE, SNAME_ATTR: "Circuit"})

        entries: list[Any] = [
            {
                "objnam": "CIRC9",
                "params": {"META": {"limits": {"min": "0", "max": "100"}}},
            },
        ]
        assert model.add_objects(entries) == ["CIRC9"]

        entries[0]["params"]["META"]["limits"]["max"] = "9999"

        circuit = model["CIRC9"]
        assert circuit is not None
        assert circuit["META"] == {"limits": {"min": "0", "max": "100"}}

    def test_nested_mutation_after_add_objects_does_not_affect_model(self):
        """The batch ingest path (add_objects) is nested-mutation isolated too."""
        model = PoolModel()
        entries: list[Any] = [
            {
                "objnam": "SHOW1",
                "params": {
                    OBJTYP_ATTR: CIRCUIT_TYPE,
                    SUBTYP_ATTR: "LITSHO",
                    "USE": ["C1", "C2"],
                },
            },
        ]
        model.add_objects(entries)

        entries[0]["params"]["USE"].append("HACKED")

        show = model["SHOW1"]
        assert show is not None
        assert show["USE"] == ["C1", "C2"]

    def test_add_objects_returns_added_objnams(self, pool_model_data: list[dict[str, Any]]):
        """add_objects returns the objnams it ingested (snapshot observability)."""
        model = PoolModel()

        added = model.add_objects(pool_model_data)

        assert added == [entry["objnam"] for entry in pool_model_data]
        assert model.num_objects == len(added)

        # A replay updates in place and still reports the ingested objnams.
        assert model.add_objects(pool_model_data) == added

    def test_add_objects_returns_only_ingested_objnams(self):
        """Skipped/rejected entries are absent from the returned objnams."""
        model = PoolModel(attribute_map={CIRCUIT_TYPE: {STATUS_ATTR}})
        objects: list[Any] = [
            {"objnam": "VALID1", "params": {OBJTYP_ATTR: CIRCUIT_TYPE}},
            {"params": {OBJTYP_ATTR: CIRCUIT_TYPE}},  # malformed: missing objnam
            {"objnam": "_FDR", "params": {}},  # rejected: missing OBJTYP
            {"objnam": "PUMP1", "params": {OBJTYP_ATTR: PUMP_TYPE}},  # untracked type
            {"objnam": "VALID2", "params": {OBJTYP_ATTR: CIRCUIT_TYPE}},
        ]

        added = model.add_objects(objects)

        assert added == ["VALID1", "VALID2"]
        assert model.num_objects == 2

    def test_add_objects_warns_with_counts_when_entries_skipped(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Malformed snapshot entries produce a WARNING with per-call counts."""
        model = PoolModel()
        objects: list[Any] = [
            {"params": {OBJTYP_ATTR: CIRCUIT_TYPE}},  # missing objnam
            {"objnam": "BADPARAMS", "params": "garbage"},  # params not a dict
            {"objnam": "VALID1", "params": {OBJTYP_ATTR: CIRCUIT_TYPE}},
        ]

        with caplog.at_level(logging.WARNING, logger="pyintellicenter.model"):
            added = model.add_objects(objects)

        assert added == ["VALID1"]
        warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "2" in message  # skipped count
        assert "3" in message  # total entries in the call
        assert "1" in message  # ingested count

    def test_add_objects_no_warning_when_all_entries_well_formed(
        self, caplog: pytest.LogCaptureFixture, pool_model_data: list[dict[str, Any]]
    ):
        """A clean snapshot (including OBJTYP-less firmware entries) stays quiet.

        Entries like _FDR (valid shape, empty params) are normal firmware
        behavior filtered by add_object at DEBUG; they must not raise the
        malformed-snapshot WARNING on every startup.
        """
        model = PoolModel()
        objects: list[Any] = [*pool_model_data, {"objnam": "_FDR", "params": {}}]

        with caplog.at_level(logging.WARNING, logger="pyintellicenter.model"):
            model.add_objects(objects)

        assert [rec for rec in caplog.records if rec.levelno >= logging.WARNING] == []
