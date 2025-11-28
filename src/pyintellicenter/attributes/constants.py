"""Type and attribute name constants for Pentair IntelliCenter."""

from enum import IntEnum

# Special object name for null/empty references
NULL_OBJNAM = "00000"

# Status values for different object types
STATUS_ON = "ON"
STATUS_OFF = "OFF"
PUMP_STATUS_ON = "10"
PUMP_STATUS_OFF = "4"

# Light subtypes that represent illumination devices
LIGHT_SUBTYPES = frozenset(["LIGHT", "INTELLI", "GLOW", "GLOWT", "DIMMER", "MAGIC2"])

# Light subtypes that support color effects
COLOR_EFFECT_SUBTYPES = frozenset(["INTELLI", "MAGIC2", "GLOW"])

# Mapping of IntelliCenter color effect codes to human-readable names
# Used with the USE attribute on lights with COLOR_EFFECT_SUBTYPES
LIGHT_EFFECTS: dict[str, str] = {
    "PARTY": "Party Mode",
    "CARIB": "Caribbean",
    "SSET": "Sunset",
    "ROMAN": "Romance",
    "AMERCA": "American",
    "ROYAL": "Royal",
    "WHITER": "White",
    "REDR": "Red",
    "BLUER": "Blue",
    "GREENR": "Green",
    "MAGNTAR": "Magenta",
}


class HeaterType(IntEnum):
    """Heater mode types for SetHeatMode command.

    These values correspond to the MODE parameter used by IntelliCenter
    to control heater operation.
    """

    NO_CHANGE = 0
    OFF = 1
    HEATER = 2
    SOLAR_ONLY = 3
    SOLAR_PREFERRED = 4
    ULTRA_TEMP = 5
    ULTRA_TEMP_PREFERRED = 6
    HYBRID_GAS = 7
    HYBRID_ULTRA_TEMP = 8
    HYBRID_HYBRID = 9
    HYBRID_DUAL = 10
    MASTER_TEMP = 11
    MAX_E_THERM = 12
    ETI_250 = 13


# Object type constants
BODY_TYPE = "BODY"
CHEM_TYPE = "CHEM"
CIRCUIT_TYPE = "CIRCUIT"
CIRCGRP_TYPE = "CIRCGRP"
EXTINSTR_TYPE = "EXTINSTR"
FEATR_TYPE = "FEATR"
HEATER_TYPE = "HEATER"
MODULE_TYPE = "MODULE"
PANEL_TYPE = "PANEL"
PERMIT_TYPE = "PERMIT"
PMPCIRC_TYPE = "PMPCIRC"
PRESS_TYPE = "PRESS"
PUMP_TYPE = "PUMP"
REMBTN_TYPE = "REMBTN"
REMOTE_TYPE = "REMOTE"
SCHED_TYPE = "SCHED"
SENSE_TYPE = "SENSE"
SYSTEM_TYPE = "SYSTEM"
SYSTIM_TYPE = "SYSTIM"
VALVE_TYPE = "VALVE"

# Attribute name constants (alphabetically sorted)
ACT_ATTR = "ACT"
ASSIGN_ATTR = "ASSIGN"
ALK_ATTR = "ALK"
AVAIL_ATTR = "AVAIL"
BODY_ATTR = "BODY"
BOOST_ATTR = "BOOST"
CALIB_ATTR = "CALIB"
CALC_ATTR = "CALC"
CYACID_ATTR = "CYACID"
CIRCUIT_ATTR = "CIRCUIT"
COMUART_ATTR = "COMUART"
COOLING_ATTR = "COOLING"
DLY_ATTR = "DLY"
ENABLE_ATTR = "ENABLE"
FEATR_ATTR = "FEATR"
FREEZE_ATTR = "FREEZE"
GPM_ATTR = "GPM"
GROUP_ATTR = "GROUP"
HEATER_ATTR = "HEATER"
HEATING_ATTR = "HEATING"
HITMP_ATTR = "HITMP"
HNAME_ATTR = "HNAME"
HTMODE_ATTR = "HTMODE"
LISTORD_ATTR = "LISTORD"
LOTMP_ATTR = "LOTMP"
LSTTMP_ATTR = "LSTTMP"
MAX_ATTR = "MAX"
MAXF_ATTR = "MAXF"
MIN_ATTR = "MIN"
MINF_ATTR = "MINF"
MODE_ATTR = "MODE"
NORMAL_ATTR = "NORMAL"
OBJTYP_ATTR = "OBJTYP"
ORPHI_ATTR = "ORPHI"
ORPLO_ATTR = "ORPLO"
ORPSET_ATTR = "ORPSET"
ORPTNK_ATTR = "ORPTNK"
ORPVAL_ATTR = "ORPVAL"
PARENT_ATTR = "PARENT"
PERMIT_ATTR = "PERMIT"
PHHI_ATTR = "PHHI"
PHLO_ATTR = "PHLO"
PHSET_ATTR = "PHSET"
PHTNK_ATTR = "PHTNK"
PHVAL_ATTR = "PHVAL"
PORT_ATTR = "PORT"
PRIM_ATTR = "PRIM"
PROBE_ATTR = "PROBE"
PROPNAME_ATTR = "PROPNAME"
PWR_ATTR = "PWR"
QUALTY_ATTR = "QUALTY"
READY_ATTR = "READY"
RPM_ATTR = "RPM"
SALT_ATTR = "SALT"
SEC_ATTR = "SEC"
SELECT_ATTR = "SELECT"
SETTMP_ATTR = "SETTMP"
SHOMNU_ATTR = "SHOMNU"
SMTSRT_ATTR = "SMTSRT"
SNAME_ATTR = "SNAME"
SOURCE_ATTR = "SOURCE"
SPEED_ATTR = "SPEED"
STATIC_ATTR = "STATIC"
STATUS_ATTR = "STATUS"
SUBTYP_ATTR = "SUBTYP"
SUPER_ATTR = "SUPER"
TEMP_ATTR = "TEMP"
TIME_ATTR = "TIME"
TIMOUT_ATTR = "TIMOUT"
UPDATE_ATTR = "UPDATE"
USE_ATTR = "USE"
VACFLO_ATTR = "VACFLO"
VACTIM_ATTR = "VACTIM"
VER_ATTR = "VER"
VOL_ATTR = "VOL"

# User privileges mapping
USER_PRIVILEGES = {
    "p": "Pool Access",
    "P": "Pool temperature",
    "h": "Pool Heat Mode",
    "m": "Spa Access",
    "S": "Spa Temperature",
    "n": "Spa Heat Mode",
    "e": "Schedule Access",
    "v": "Vacation Mode",
    "f": "Features Access",
    "l": "Lights Access",
    "c": "Chemistry Access",
    "u": "Usage Access",
    "C": "System Configuration",
    "o": "Support",
    "q": "Alerts and Notifications",
    "i": "User Portal",
    "k": "Groups",
    "a": "Advanced Settings",
    "t": "Status",
    "x": "Service Mode Circuits",
    "g": "General Settings",
}
