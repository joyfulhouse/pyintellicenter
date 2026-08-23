"""Tests for the public export surface of the package."""

import pyintellicenter
from pyintellicenter import attributes

DISCOVERY_EXPORTS = [
    "ICUnit",
    "discover_intellicenter_units",
    "find_unit_by_name",
    "find_unit_by_host",
    "DEFAULT_DISCOVERY_TIMEOUT",
]

ALIGNED_ATTR_EXPORTS = [
    "ASSIGN_ATTR",
    "CALIB_ATTR",
    "PORT_ATTR",
    "PROBE_ATTR",
    "SETTMP_ATTR",
]


class TestRootExports:
    """Tests for pyintellicenter.__all__."""

    def test_all_names_resolve(self):
        """Every name in __all__ must be importable from the package."""
        for name in pyintellicenter.__all__:
            assert hasattr(pyintellicenter, name), f"{name} is in __all__ but not defined"

    def test_no_duplicates_in_all(self):
        """__all__ must not contain duplicate entries."""
        assert len(pyintellicenter.__all__) == len(set(pyintellicenter.__all__))

    def test_discovery_exports_unconditional(self):
        """Discovery names are always exported (zeroconf is a hard dependency)."""
        for name in DISCOVERY_EXPORTS:
            assert name in pyintellicenter.__all__, f"{name} missing from __all__"
            assert hasattr(pyintellicenter, name)
        # The dead optional-zeroconf guard must stay removed
        assert not hasattr(pyintellicenter, "_DISCOVERY_AVAILABLE")

    def test_attr_constants_aligned_with_attributes_package(self):
        """Every *_ATTR name exported by attributes is exported at the root."""
        attr_names = {name for name in attributes.__all__ if name.endswith("_ATTR")}
        missing = attr_names - set(pyintellicenter.__all__)
        assert not missing, f"attributes exports missing from root __all__: {sorted(missing)}"


class TestAttributesExports:
    """Tests for pyintellicenter.attributes.__all__."""

    def test_all_names_resolve(self):
        """Every name in attributes.__all__ must be importable."""
        for name in attributes.__all__:
            assert hasattr(attributes, name), f"{name} is in __all__ but not defined"

    def test_no_duplicates_in_all(self):
        """attributes.__all__ must not contain duplicate entries."""
        assert len(attributes.__all__) == len(set(attributes.__all__))

    def test_settmp_and_port_exported(self):
        """SETTMP_ATTR and PORT_ATTR are used by attribute sets and must be exported."""
        for name in ("SETTMP_ATTR", "PORT_ATTR"):
            assert name in attributes.__all__
            assert name in pyintellicenter.__all__

    def test_aligned_attrs_exported_from_root(self):
        """Constants surfaced by the attributes package are re-exported at the root."""
        for name in ALIGNED_ATTR_EXPORTS:
            assert name in attributes.__all__, f"{name} missing from attributes.__all__"
            assert name in pyintellicenter.__all__, f"{name} missing from root __all__"
            assert getattr(pyintellicenter, name) == getattr(attributes, name)
