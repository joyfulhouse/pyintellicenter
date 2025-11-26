"""Equipment attribute definitions (pumps, heaters, chemistry, sensors)."""

from .constants import (
    BODY_ATTR,
    CIRCUIT_ATTR,
    COMUART_ATTR,
    DLY_ATTR,
    GPM_ATTR,
    HNAME_ATTR,
    HTMODE_ATTR,
    LISTORD_ATTR,
    MODE_ATTR,
    ORPTNK_ATTR,
    ORPVAL_ATTR,
    PARENT_ATTR,
    PHTNK_ATTR,
    PHVAL_ATTR,
    PRIM_ATTR,
    PWR_ATTR,
    QUALTY_ATTR,
    READY_ATTR,
    RPM_ATTR,
    SALT_ATTR,
    SEC_ATTR,
    SELECT_ATTR,
    SHOMNU_ATTR,
    SNAME_ATTR,
    SOURCE_ATTR,
    STATIC_ATTR,
    STATUS_ATTR,
    SUBTYP_ATTR,
    SUPER_ATTR,
    TIME_ATTR,
    TIMOUT_ATTR,
)

# Chemistry controller attributes (IntelliChlor, IntelliChem)
CHEM_ATTRIBUTES = {
    "ALK",  # (int) IntelliChem: Alkalinity setting
    BODY_ATTR,  # (objnam) BODY being managed
    "CALC",  # (int) IntelliChem: Calcium Harness setting
    "CHLOR",  # (ON/OFF) IntelliChem: ??
    COMUART_ATTR,  # (int) X25 related ?
    "CYACID",  # (int) IntelliChem: Cyanuric Acid setting
    LISTORD_ATTR,  # (int) used to order in UI
    "ORPHI",  # (ON/OFF) IntelliChem: ORP Level too high?
    "ORPLO",  # (ON/OFF) IntelliChem: ORP Level too low?
    "ORPSET",  # (int) IntelliChem ORP level setting
    ORPTNK_ATTR,  # (int) IntelliChem: ORP Tank Level
    ORPVAL_ATTR,  # (int) IntelliChem: ORP Level
    "PHHI",  # (ON/OFF) IntelliChem: Ph Level too low?
    "PHLO",  # (ON/OFF) IntelliChem: Ph Level too low?
    "PHSET",  # (float) IntelliChem Ph level setting
    PHTNK_ATTR,  # (int) IntelliChem: Ph Tank Level
    PHVAL_ATTR,  # (float) IntelliChem: Ph Level
    PRIM_ATTR,  # (int) IntelliChlor: primary body output setting in %
    QUALTY_ATTR,  # (float) IntelliChem: Water Quality (Saturation Index)
    SALT_ATTR,  # (int) Salt level
    SEC_ATTR,  # (int) IntelliChlor: secondary body output setting in %
    "SHARE",  # (objnam) ??
    "SINDEX",  # (int) ??
    SNAME_ATTR,  # friendly name
    SUBTYP_ATTR,  # 'ICHLOR' for IntelliChlor, 'ICHEM' for IntelliChem
    SUPER_ATTR,  # (ON/OFF) IntelliChlor: turn on Boost mode (aka Super Chlorinate)
    TIMOUT_ATTR,  # (int) IntelliChlor: in seconds ??
}

# Heater attributes
# Matches node-intellicenter GetHeaters attributes
HEATER_ATTRIBUTES = {
    BODY_ATTR,  # the objnam of the body the heater serves or a list (separated by a space)
    "BOOST",  # (int) Boost mode setting
    COMUART_ATTR,  # X25 related?
    "COOL",  # (ON/OFF) Cooling mode
    DLY_ATTR,  # (int) Delay setting
    "HEATING",  # (ON/OFF) Currently heating
    HNAME_ATTR,  # equals to OBJNAM
    HTMODE_ATTR,  # (int) Heat mode setting
    LISTORD_ATTR,  # (int) used to order in UI
    MODE_ATTR,  # (int) Current operating mode (see HeaterType enum)
    PARENT_ATTR,  # (objnam) parent (module) for this heater
    "PERMIT",  # (str) Permissions
    READY_ATTR,  # (ON/OFF) Ready state
    SHOMNU_ATTR,  # (str) Menu permissions
    SNAME_ATTR,  # (str) Friendly name
    "START",  # (int) Start time
    STATIC_ATTR,  # (ON/OFF) Static setting
    STATUS_ATTR,  # (ON/OFF) Only seen 'ON'
    "STOP",  # (int) Stop time
    SUBTYP_ATTR,  # type of heater 'GENERIC','SOLAR','ULTRA','HEATER'
    TIME_ATTR,  # (int) Time setting
    TIMOUT_ATTR,  # (int) Timeout setting
}

# Pump attributes
PUMP_ATTRIBUTES = {
    BODY_ATTR,  # the objnam of the body the pump serves or a list (separated by a space)
    CIRCUIT_ATTR,  # (int) ??? only seen 1
    COMUART_ATTR,  # X25 related?
    HNAME_ATTR,  # same as objnam
    GPM_ATTR,  # (int) when applicable, real time Gallon Per Minute
    LISTORD_ATTR,  # (int) used to order in UI
    "MAX",  # (int) maximum RPM
    "MAXF",  # (int) maximum GPM (if applicable, 0 otherwise)
    "MIN",  # (int) minimum RPM
    "MINF",  # (int) minimum GPM (if applicable, 0 otherwise)
    "NAME",  # seems to equal OBJNAM
    "OBJLIST",  # ([ objnam] ) a list of PMPCIRC settings
    "PRIMFLO",  # (int) Priming Speed
    "PRIMTIM",  # (int) Priming Time in minutes
    "PRIOR",  # (int) ???
    PWR_ATTR,  # (int) when applicable, real time Power usage in Watts
    RPM_ATTR,  # (int) when applicable, real time Rotation Per Minute
    "SETTMP",  # (int) Step size for RPM
    "SETTMPNC",  # (int) ???
    SNAME_ATTR,  # friendly name
    STATUS_ATTR,  # only seen 10 for on, 4 for off
    SUBTYP_ATTR,  # type of pump: 'SPEED' (variable speed), 'FLOW' (variable flow), 'VSF' (both)
    "SYSTIM",  # (int) ???
}

# Pump circuit setting attributes
PMPCIRC_ATTRIBUTES = {
    BODY_ATTR,  # not sure, I've only see '00000'
    CIRCUIT_ATTR,  # (objnam) the circuit this setting is for
    GPM_ATTR,  # (int): the flow setting for the pump if select is GPM
    LISTORD_ATTR,  # (int) used to order in UI
    PARENT_ATTR,  # (objnam) the pump the setting belongs to
    "SPEED",  # (int): the speed setting for the pump if select is RPM
    SELECT_ATTR,  # 'RPM' or 'GPM'
}

# Sensor attributes
SENSE_ATTRIBUTES = {
    "CALIB",  # (int) calibration value
    HNAME_ATTR,  # same as objnam
    LISTORD_ATTR,  # number likely used to order things in UI
    MODE_ATTR,  # I've only seen 'OFF' so far
    "NAME",  # I've only seen '00000'
    PARENT_ATTR,  # the parent's objnam
    "PROBE",  # the uncalibrated reading of the sensor
    SNAME_ATTR,  # friendly name
    SOURCE_ATTR,  # the calibrated reading of the sensor
    STATIC_ATTR,  # (ON/OFF) not sure, only seen 'ON'
    STATUS_ATTR,  # I've only seen 'OK' so far
    SUBTYP_ATTR,  # 'SOLAR','POOL' (for water), 'AIR'
}
