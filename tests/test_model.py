"""Tests for PoolModel and PoolObject classes."""

from collections.abc import KeysView
from typing import Any

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
        """Test properties property returns dict."""
        props = pool_object_light.properties
        assert isinstance(props, dict)
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
        """Test objects property returns dict."""
        objects_dict = pool_model.objects
        assert isinstance(objects_dict, dict)
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
        """Test processing updates for non-existent object."""
        updates = [
            {
                "objnam": "UNKNOWN",
                "params": {STATUS_ATTR: "ON"},
            },
        ]

        changed = pool_model.process_updates(updates)

        assert changed == {}

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
