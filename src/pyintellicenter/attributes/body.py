"""Body of water (pool/spa) attribute definitions."""

from .constants import (
    BOOST_ATTR,
    CIRCUIT_ATTR,
    HEATER_ATTR,
    HNAME_ATTR,
    HTMODE_ATTR,
    LISTORD_ATTR,
    LOTMP_ATTR,
    LSTTMP_ATTR,
    MODE_ATTR,
    PARENT_ATTR,
    PRIM_ATTR,
    READY_ATTR,
    SEC_ATTR,
    SELECT_ATTR,
    SNAME_ATTR,
    SPEED_ATTR,
    STATIC_ATTR,
    STATUS_ATTR,
    SUBTYP_ATTR,
    TEMP_ATTR,
    VOL_ATTR,
)

# Represents a body of water (pool or spa)
# Matches node-intellicenter GetBodyStatus attributes
BODY_ATTRIBUTES = {
    "ACT1",  # (int) Activity setting 1
    "ACT2",  # (int) Activity setting 2
    "ACT3",  # (int) Activity setting 3
    "ACT4",  # (int) Activity setting 4
    BOOST_ATTR,  # (ON/OFF) Boost heating enabled
    CIRCUIT_ATTR,  # (objnam) Associated circuit
    "FILTER",  # (objnam) Circuit object that filters this body
    HEATER_ATTR,  # (objnam) Associated heater
    "HITMP",  # (int) Maximum temperature setting
    HNAME_ATTR,  # equals to OBJNAM
    HTMODE_ATTR,  # (int) >0 if currently heating, 0 if not
    "HTSRC",  # (objnam) the heating source (or '00000')
    LISTORD_ATTR,  # (int) used to order in UI
    LOTMP_ATTR,  # (int) Desired temperature setpoint
    LSTTMP_ATTR,  # (int) Last recorded temperature
    "MANHT",  # Manual heating
    "MANUAL",  # (int) Manual mode
    MODE_ATTR,  # (str) Current mode
    PARENT_ATTR,  # (objnam) parent object
    PRIM_ATTR,  # (int) Primary setting
    READY_ATTR,  # (ON/OFF) Ready state
    SEC_ATTR,  # (int) Secondary setting
    SELECT_ATTR,  # (str) Selection mode
    "SETPT",  # (int) Set point (same as LOTMP)
    "SHARE",  # (objnam) Sharing with other body
    SNAME_ATTR,  # (str) Friendly name
    SPEED_ATTR,  # (int) Speed setting
    "SRCTYP",  # Source type (e.g., "GENERIC")
    STATIC_ATTR,  # (ON/OFF) Static setting
    STATUS_ATTR,  # (ON/OFF) 'ON' if body is "active"
    SUBTYP_ATTR,  # 'POOL' or 'SPA'
    TEMP_ATTR,  # (int) Current temperature
    VOL_ATTR,  # (int) Volume in Gallons
}
