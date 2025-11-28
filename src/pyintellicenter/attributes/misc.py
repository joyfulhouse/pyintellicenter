"""Miscellaneous attribute definitions (remote, valve, external instruments, etc.)."""

from .constants import (
    ASSIGN_ATTR,
    BODY_ATTR,
    CIRCUIT_ATTR,
    COMUART_ATTR,
    DLY_ATTR,
    ENABLE_ATTR,
    HNAME_ATTR,
    LISTORD_ATTR,
    NORMAL_ATTR,
    PARENT_ATTR,
    READY_ATTR,
    SHOMNU_ATTR,
    SNAME_ATTR,
    SOURCE_ATTR,
    STATIC_ATTR,
    STATUS_ATTR,
    SUBTYP_ATTR,
)

# External instrument attributes (covers, etc.)
EXTINSTR_ATTRIBUTES = {
    BODY_ATTR,  # (objnam) which body it covers
    HNAME_ATTR,  # equals to OBJNAM
    LISTORD_ATTR,  # (int) used to order in UI
    NORMAL_ATTR,  # (ON/OFF) 'ON' for Cover State Normally On
    PARENT_ATTR,  # (objnam)
    READY_ATTR,  # (ON/OFF) ???
    SNAME_ATTR,  # (str) friendly name
    STATIC_ATTR,  # (ON/OFF) 'OFF'
    STATUS_ATTR,  # (ON/OFF) 'ON' if cover enabled
    SUBTYP_ATTR,  # only seen 'COVER'
}

# Feature attributes (no idea what this represents)
FEATR_ATTRIBUTES = {
    HNAME_ATTR,
    LISTORD_ATTR,
    READY_ATTR,
    SNAME_ATTR,
    SOURCE_ATTR,
    STATIC_ATTR,
}

# Press attributes (no idea what this object type represents)
# Only seems to be one instance of it
PRESS_ATTRIBUTES = {
    READY_ATTR,  # (ON/OFF) Ready state
    SHOMNU_ATTR,  # (ON/OFF) ???
    SNAME_ATTR,  # seems equal to objnam
    STATIC_ATTR,  # (ON/OFF) only seen ON
}

# Remote button mapping attributes
REMBTN_ATTRIBUTES = {
    CIRCUIT_ATTR,  # (objnam) the circuit triggered by the button
    LISTORD_ATTR,  # (int) which button on the remote (1 to 4)
    PARENT_ATTR,  # (objnam) the remote this button is associated with
    READY_ATTR,  # (ON/OFF) Ready state
    STATIC_ATTR,  # (ON/OFF) not sure, only seen 'ON'
}

# Remote attributes
REMOTE_ATTRIBUTES = {
    BODY_ATTR,  # (objnam) the body the remote controls
    COMUART_ATTR,  # X25 address?
    ENABLE_ATTR,  # (ON/OFF) 'ON' if the remote is set to active
    HNAME_ATTR,  # same as objnam
    LISTORD_ATTR,  # number likely used to order things in UI
    READY_ATTR,  # (ON/OFF) Ready state
    SNAME_ATTR,  # friendly name
    STATIC_ATTR,  # (ON/OFF) not sure, only seen 'OFF'
    SUBTYP_ATTR,  # type of the remote, I've only seen IS4
}

# Valve attributes
# Note: Legacy valves don't have a STATUS attribute - valve position is
# controlled automatically by the system based on which body circuit is active
VALVE_ATTRIBUTES = {
    ASSIGN_ATTR,  # 'NONE', 'INTAKE' or 'RETURN' - valve role assignment
    CIRCUIT_ATTR,  # I've only seen '00000'
    DLY_ATTR,  # (ON/OFF) delay setting
    HNAME_ATTR,  # same as objnam
    PARENT_ATTR,  # (objnam) parent (a module)
    READY_ATTR,  # (ON/OFF) Ready state
    SNAME_ATTR,  # friendly name
    STATIC_ATTR,  # (ON/OFF) I've only seen 'OFF'
    SUBTYP_ATTR,  # 'LEGACY' for standard valve actuators
}
