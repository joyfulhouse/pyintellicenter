"""Circuit and circuit group attribute definitions."""

from .constants import (
    ACT_ATTR,
    BODY_ATTR,
    CIRCUIT_ATTR,
    DLY_ATTR,
    FEATR_ATTR,
    FREEZE_ATTR,
    HNAME_ATTR,
    LISTORD_ATTR,
    PARENT_ATTR,
    READY_ATTR,
    SELECT_ATTR,
    SHOMNU_ATTR,
    SNAME_ATTR,
    STATIC_ATTR,
    STATUS_ATTR,
    SUBTYP_ATTR,
    TIME_ATTR,
    USE_ATTR,
)

# Circuit attributes
CIRCUIT_ATTRIBUTES = {
    ACT_ATTR,  # to be set for changing USE attribute
    BODY_ATTR,
    "CHILD",
    "COVER",
    "DNTSTP",  # (ON/OFF) "Don't Stop", disable egg timer
    FEATR_ATTR,  # (ON/OFF) Featured
    FREEZE_ATTR,  # (ON/OFF) Freeze Protection
    HNAME_ATTR,  # equals to OBJNAM
    "LIMIT",
    LISTORD_ATTR,  # (int) used to order in UI
    "OBJLIST",
    PARENT_ATTR,  # OBJNAM of the parent object
    READY_ATTR,  # (ON/OFF) ??
    SELECT_ATTR,  # ???
    "SET",  # (ON/OFF) for light groups only
    SHOMNU_ATTR,  # (str) permissions
    SNAME_ATTR,  # (str) friendly name
    STATIC_ATTR,  # (ON/OFF) ??
    STATUS_ATTR,  # (ON/OFF) 'ON' if circuit is active
    SUBTYP_ATTR,  # subtype can be '?
    "SWIM",  # (ON/OFF) for light groups only
    "SYNC",  # (ON/OFF) for light groups only
    TIME_ATTR,  # (int) Egg Timer, number of minutes
    "USAGE",
    USE_ATTR,  # for lights with light effects, indicate the 'color'
}

# Circuit group attributes
CIRCGRP_ATTRIBUTES = {
    ACT_ATTR,
    CIRCUIT_ATTR,
    DLY_ATTR,
    LISTORD_ATTR,
    PARENT_ATTR,
    READY_ATTR,
    SNAME_ATTR,
    STATIC_ATTR,
    STATUS_ATTR,
    USE_ATTR,  # (str) Light effect for circuit groups (e.g., "Lavender", "Blue", "White")
}
