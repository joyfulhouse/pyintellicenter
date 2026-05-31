"""Guard the public module namespace of ``pyintellicenter.controller``.

Several attribute/type constants (e.g. ``BODY_TYPE``, ``PUMP_TYPE``,
``TEMP_ATTR``, ``VACFLO_ATTR``) were historically importable directly from the
``pyintellicenter.controller`` submodule because the controller imported them at
module scope for its own use.

The mixin refactor moved the helper methods that used those constants into
``pyintellicenter._mixins``. That dropped their only *local* uses from
``controller.py``, which would otherwise let an import-cleanup remove them and
silently break any consumer doing ``from pyintellicenter.controller import X``.

To keep the refactor behavior-preserving at the module-namespace level, the
controller re-exports every such name. This test pins that contract so future
refactor steps cannot regress it: each name below must resolve from
``pyintellicenter.controller``.
"""

from __future__ import annotations

import pytest

import pyintellicenter.controller as controller_module

# The complete set of public names imported at module scope from ``.attributes``
# by the original (pre-refactor) controller.py. Every one of these must remain
# accessible as ``pyintellicenter.controller.<NAME>``.
HISTORICAL_ATTRIBUTE_NAMES = [
    "ACT_ATTR",
    "ALK_ATTR",
    "ASSIGN_ATTR",
    "BODY_ATTR",
    "BODY_TYPE",
    "CALC_ATTR",
    "CHEM_TYPE",
    "CIRCGRP_TYPE",
    "CIRCUIT_ATTR",
    "CIRCUIT_TYPE",
    "CYACID_ATTR",
    "EXTINSTR_TYPE",
    "GPM_ATTR",
    "HEATER_ATTR",
    "HEATER_TYPE",
    "HITMP_ATTR",
    "HTMODE_ATTR",
    "LIGHT_EFFECTS",
    "LOTMP_ATTR",
    "MAX_ATTR",
    "MAXF_ATTR",
    "MIN_ATTR",
    "MINF_ATTR",
    "MODE_ATTR",
    "NULL_OBJNAM",
    "OBJTYP_ATTR",
    "ORPHI_ATTR",
    "ORPLO_ATTR",
    "ORPSET_ATTR",
    "ORPVAL_ATTR",
    "PARENT_ATTR",
    "PHHI_ATTR",
    "PHLO_ATTR",
    "PHSET_ATTR",
    "PHVAL_ATTR",
    "PMPCIRC_TYPE",
    "PRIM_ATTR",
    "PROPNAME_ATTR",
    "PUMP_STATUS_ON",
    "PUMP_TYPE",
    "PWR_ATTR",
    "QUALTY_ATTR",
    "RPM_ATTR",
    "SALT_ATTR",
    "SCHED_TYPE",
    "SEC_ATTR",
    "SELECT_ATTR",
    "SENSE_TYPE",
    "SNAME_ATTR",
    "SOURCE_ATTR",
    "SPEED_ATTR",
    "STATUS_ATTR",
    "STATUS_OFF",
    "STATUS_ON",
    "SUBTYP_ATTR",
    "SUPER_ATTR",
    "SYSTEM_TYPE",
    "TEMP_ATTR",
    "USE_ATTR",
    "VACFLO_ATTR",
    "VALVE_TYPE",
    "VER_ATTR",
    "HeaterType",
]


@pytest.mark.parametrize("name", HISTORICAL_ATTRIBUTE_NAMES)
def test_attribute_constant_importable_from_controller(name: str) -> None:
    """Each historical attribute/type constant must resolve from the controller module."""
    assert hasattr(controller_module, name), (
        f"pyintellicenter.controller.{name} is no longer importable; "
        "the mixin refactor must preserve the controller module namespace"
    )


def test_constant_values_match_attributes_module() -> None:
    """Re-exported names must be the same objects as in ``pyintellicenter.attributes``."""
    from pyintellicenter import attributes

    for name in HISTORICAL_ATTRIBUTE_NAMES:
        assert getattr(controller_module, name) is getattr(attributes, name), (
            f"pyintellicenter.controller.{name} differs from pyintellicenter.attributes.{name}"
        )
