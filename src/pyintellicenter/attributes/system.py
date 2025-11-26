"""System, panel, module, permit, and clock attribute definitions."""

from .constants import (
    ACT_ATTR,
    ENABLE_ATTR,
    HNAME_ATTR,
    LISTORD_ATTR,
    MODE_ATTR,
    PARENT_ATTR,
    PROPNAME_ATTR,
    SHOMNU_ATTR,
    SNAME_ATTR,
    SOURCE_ATTR,
    STATIC_ATTR,
    STATUS_ATTR,
    SUBTYP_ATTR,
    TIMOUT_ATTR,
    VACFLO_ATTR,
    VER_ATTR,
)

# System attributes (unique instance)
SYSTEM_ATTRIBUTES = {
    ACT_ATTR,  # ON/OFF but not sure what it does
    "ADDRESS",  # Pool Address
    "AVAIL",  # ON/OFF but not sure what it does
    "CITY",  # Pool City
    "COUNTRY",  # Country obviously (example 'United States')
    "EMAIL",  # primary email for the owner
    "EMAIL2",  # secondary email for the owner
    "HEATING",  # ON/OFF: Pump On During Heater Cool-Down Delay
    HNAME_ATTR,  # same as objnam
    "LOCX",  # (float) longitude
    "LOCY",  # (float) latitude
    "MANHT",  # ON/OFF: Manual Heat
    MODE_ATTR,  # unit system, 'METRIC' or 'ENGLISH'
    "NAME",  # name of the owner
    "PASSWRD",  # a 4 digit password or ''
    "PHONE",  # primary phone number for the owner
    "PHONE2",  # secondary phone number for the owner
    PROPNAME_ATTR,  # name of the property
    "SERVICE",  # 'AUTO' for automatic
    SNAME_ATTR,  # a crazy looking string I assume to be unique to this system
    "START",  # almost looks like a date but no idea
    "STATE",  # Pool State
    STATUS_ATTR,  # ON/OFF
    "STOP",  # same value as START
    "TEMPNC",  # ON/OFF
    "TIMZON",  # (int) Time Zone (example '-8' for US Pacific)
    VACFLO_ATTR,  # ON/OFF, vacation mode
    "VACTIM",  # ON/OFF
    "VALVE",  # ON/OFF: Pump Off During Valve Action
    VER_ATTR,  # (str) software version
    "ZIP",  # Pool Zip Code
}

# System clock attributes
# Note: there are 2 clocks in the system
# one only contains the SOURCE attribute
# the other everything but SOURCE
SYSTIM_ATTRIBUTES = {
    "CLK24A",  # clock mode, 'AMPM' or 'HR24'
    "DAY",  # in 'MM,DD,YY' format
    "DLSTIM",  # ON/OFF, ON for following DST
    HNAME_ATTR,  # same as objnam
    "LOCX",  # (float) longitude
    "LOCY",  # (float) latitude
    "MIN",  # in 'HH,MM,SS' format (24h clock)
    SNAME_ATTR,  # unused really, likely equals to OBJNAM
    SOURCE_ATTR,  # set to URL if time is from the internet
    STATIC_ATTR,  # (ON/OFF) not sure, only seen 'ON'
    "TIMZON",  # (int) timezone (example '-8' for US Pacific)
    "ZIP",  # ZipCode
}

# Panel attributes
PANEL_ATTRIBUTES = {
    HNAME_ATTR,  # equals to OBJNAM
    LISTORD_ATTR,  # (int) used to order in UI
    "OBJLIST",  # [ (objnam) ] the elements managed by the panel
    "PANID",  # ??? only seen 'SHARE'
    SNAME_ATTR,  # friendly name
    STATIC_ATTR,  # only seen 'ON'
    SUBTYP_ATTR,  # only seen 'OCP'
}

# Module attributes
MODULE_ATTRIBUTES = {
    "CIRCUITS",  # [ objects ] the objects that the module controls
    PARENT_ATTR,  # (objnam) the parent (PANEL) of the module
    "PORT",  # (int) no idea
    SNAME_ATTR,  # friendly name
    STATIC_ATTR,  # (ON/OFF) 'ON'
    SUBTYP_ATTR,  # type of the module (like 'I5P' or 'I8PS')
    VER_ATTR,  # (str) the version of the firmware for this module
}

# User/permit attributes
PERMIT_ATTRIBUTES = {
    ENABLE_ATTR,  # (ON/OFF) ON if user is enabled
    "PASSWRD",  # 4 digit code or ''
    SHOMNU_ATTR,  # privileges associated with this user
    SNAME_ATTR,  # friendly name
    STATIC_ATTR,  # (ON/OFF) only seen ON
    SUBTYP_ATTR,  # ADV for administrator, BASIC for guest
    TIMOUT_ATTR,  # (int) in minutes, timeout for user session
}
