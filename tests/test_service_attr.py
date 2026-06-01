"""Tests for the SYSTEM ``SERVICE`` attribute constant.

The SYSTEM object's ``SERVICE`` attribute reports the pool's operating mode
(known value ``'AUTO'`` for normal automatic operation; Service/Timeout modes
are documented but not yet hardware-confirmed). This test pins that the
attribute key is promoted to a named, exported ``SERVICE_ATTR`` constant,
mirroring the existing ``MODE_ATTR``/``VACFLO_ATTR``/``VER_ATTR`` constants.
"""

from __future__ import annotations


class TestServiceAttr:
    """Pin the public export contract for ``SERVICE_ATTR``."""

    def test_importable_from_top_level(self) -> None:
        """``SERVICE_ATTR`` must be importable from the top-level package."""
        from pyintellicenter import SERVICE_ATTR

        assert SERVICE_ATTR == "SERVICE"

    def test_importable_from_attributes(self) -> None:
        """``SERVICE_ATTR`` must be importable from ``pyintellicenter.attributes``."""
        from pyintellicenter.attributes import SERVICE_ATTR

        assert SERVICE_ATTR == "SERVICE"

    def test_same_object_across_namespaces(self) -> None:
        """The top-level and attributes exports must be the same object."""
        import pyintellicenter
        from pyintellicenter import attributes

        assert pyintellicenter.SERVICE_ATTR is attributes.SERVICE_ATTR

    def test_exported_in_dunder_all(self) -> None:
        """``SERVICE_ATTR`` must be listed in both ``__all__`` exports."""
        import pyintellicenter
        from pyintellicenter import attributes

        assert "SERVICE_ATTR" in pyintellicenter.__all__
        assert "SERVICE_ATTR" in attributes.__all__

    def test_used_in_system_attributes_set(self) -> None:
        """The SYSTEM attribute set must contain the named constant value."""
        from pyintellicenter import SERVICE_ATTR
        from pyintellicenter.attributes import SYSTEM_ATTRIBUTES

        assert SERVICE_ATTR in SYSTEM_ATTRIBUTES
