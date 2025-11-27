"""pyintellicenter - Python library for Pentair IntelliCenter pool control systems.

This library provides the core protocol and model classes for communicating
with Pentair IntelliCenter pool control systems over local network.

Example usage:
    ```python
    import asyncio
    from pyintellicenter import ICModelController, PoolModel, ICConnectionHandler

    async def main():
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model)
        handler = ICConnectionHandler(controller)
        await handler.start()

        # Access pool equipment
        for obj in model:
            print(f"{obj.sname}: {obj.status}")

    asyncio.run(main())
    ```
"""

# Re-export all public names from submodules
from .attributes import (
    # Attribute name constants
    ACT_ATTR,
    ALK_ATTR,
    AVAIL_ATTR,
    BODY_ATTR,
    # Type constants
    BODY_TYPE,
    BOOST_ATTR,
    CALC_ATTR,
    CHEM_TYPE,
    CIRCGRP_TYPE,
    CIRCUIT_ATTR,
    CIRCUIT_TYPE,
    # Status constants
    COLOR_EFFECT_SUBTYPES,
    COMUART_ATTR,
    COOLING_ATTR,
    CYACID_ATTR,
    DLY_ATTR,
    ENABLE_ATTR,
    EXTINSTR_TYPE,
    FEATR_ATTR,
    FEATR_TYPE,
    FREEZE_ATTR,
    GPM_ATTR,
    GROUP_ATTR,
    HEATER_ATTR,
    HEATER_TYPE,
    HEATING_ATTR,
    HITMP_ATTR,
    HNAME_ATTR,
    HTMODE_ATTR,
    LIGHT_EFFECTS,
    LIGHT_SUBTYPES,
    LISTORD_ATTR,
    LOTMP_ATTR,
    LSTTMP_ATTR,
    MAX_ATTR,
    MAXF_ATTR,
    MIN_ATTR,
    MINF_ATTR,
    MODE_ATTR,
    MODULE_TYPE,
    NORMAL_ATTR,
    # Special values
    NULL_OBJNAM,
    OBJTYP_ATTR,
    ORPHI_ATTR,
    ORPLO_ATTR,
    ORPSET_ATTR,
    ORPTNK_ATTR,
    ORPVAL_ATTR,
    PANEL_TYPE,
    PARENT_ATTR,
    PERMIT_ATTR,
    PERMIT_TYPE,
    PHHI_ATTR,
    PHLO_ATTR,
    PHSET_ATTR,
    PHTNK_ATTR,
    PHVAL_ATTR,
    PMPCIRC_TYPE,
    PRESS_TYPE,
    PRIM_ATTR,
    PROPNAME_ATTR,
    PUMP_STATUS_OFF,
    PUMP_STATUS_ON,
    PUMP_TYPE,
    PWR_ATTR,
    QUALTY_ATTR,
    READY_ATTR,
    REMBTN_TYPE,
    REMOTE_TYPE,
    RPM_ATTR,
    SALT_ATTR,
    SCHED_TYPE,
    SEC_ATTR,
    SELECT_ATTR,
    SENSE_TYPE,
    SHOMNU_ATTR,
    SMTSRT_ATTR,
    SNAME_ATTR,
    SOURCE_ATTR,
    SPEED_ATTR,
    STATIC_ATTR,
    STATUS_ATTR,
    STATUS_OFF,
    STATUS_ON,
    SUBTYP_ATTR,
    SUPER_ATTR,
    SYSTEM_TYPE,
    SYSTIM_TYPE,
    TEMP_ATTR,
    TIME_ATTR,
    TIMOUT_ATTR,
    UPDATE_ATTR,
    USE_ATTR,
    USER_PRIVILEGES,
    VACFLO_ATTR,
    VACTIM_ATTR,
    VALVE_TYPE,
    VER_ATTR,
    VOL_ATTR,
    # Enums
    HeaterType,
)
from .connection import ICConnection, ICProtocol
from .controller import (
    ICBaseController,
    ICConnectionHandler,
    ICConnectionHandlerCallbacks,
    ICConnectionMetrics,
    ICModelController,
    ICSystemInfo,
)
from .exceptions import (
    ICCommandError,
    ICConnectionError,
    ICError,
    ICResponseError,
    ICTimeoutError,
)
from .model import PoolModel, PoolObject
from .types import (
    NotificationMessage,
    ObjectEntry,
    ObjectListRequest,
    ObjectParams,
    ResponseMessage,
)

# Discovery module (requires optional 'zeroconf' dependency)
# Import conditionally to avoid ImportError when zeroconf is not installed
try:
    from .discovery import (  # noqa: F401
        DEFAULT_DISCOVERY_TIMEOUT,
        ICUnit,
        discover_intellicenter_units,
        find_unit_by_host,
        find_unit_by_name,
    )

    _DISCOVERY_AVAILABLE = True
except ImportError:
    _DISCOVERY_AVAILABLE = False

__version__ = "0.0.5a9"

__all__ = [
    # Version
    "__version__",
    # Exceptions
    "ICError",
    "ICConnectionError",
    "ICResponseError",
    "ICCommandError",
    "ICTimeoutError",
    # Connection
    "ICConnection",
    "ICProtocol",
    # Controller classes
    "ICBaseController",
    "ICModelController",
    "ICConnectionHandler",
    "ICConnectionHandlerCallbacks",
    "ICConnectionMetrics",
    "ICSystemInfo",
    # Model classes
    "PoolModel",
    "PoolObject",
    # Type definitions
    "NotificationMessage",
    "ObjectEntry",
    "ObjectListRequest",
    "ObjectParams",
    "ResponseMessage",
    # Enums
    "HeaterType",
    # Status constants
    "STATUS_ON",
    "STATUS_OFF",
    "PUMP_STATUS_ON",
    "PUMP_STATUS_OFF",
    "LIGHT_SUBTYPES",
    "COLOR_EFFECT_SUBTYPES",
    "LIGHT_EFFECTS",
    # Object types
    "BODY_TYPE",
    "CHEM_TYPE",
    "CIRCUIT_TYPE",
    "CIRCGRP_TYPE",
    "EXTINSTR_TYPE",
    "FEATR_TYPE",
    "HEATER_TYPE",
    "MODULE_TYPE",
    "PANEL_TYPE",
    "PERMIT_TYPE",
    "PMPCIRC_TYPE",
    "PRESS_TYPE",
    "PUMP_TYPE",
    "REMBTN_TYPE",
    "REMOTE_TYPE",
    "SCHED_TYPE",
    "SENSE_TYPE",
    "SYSTEM_TYPE",
    "SYSTIM_TYPE",
    "VALVE_TYPE",
    # Special values
    "NULL_OBJNAM",
    # Attributes
    "ACT_ATTR",
    "ALK_ATTR",
    "AVAIL_ATTR",
    "BODY_ATTR",
    "BOOST_ATTR",
    "CALC_ATTR",
    "CIRCUIT_ATTR",
    "COMUART_ATTR",
    "COOLING_ATTR",
    "CYACID_ATTR",
    "DLY_ATTR",
    "ENABLE_ATTR",
    "FEATR_ATTR",
    "FREEZE_ATTR",
    "GPM_ATTR",
    "GROUP_ATTR",
    "HEATER_ATTR",
    "HEATING_ATTR",
    "HITMP_ATTR",
    "HNAME_ATTR",
    "HTMODE_ATTR",
    "LISTORD_ATTR",
    "LOTMP_ATTR",
    "LSTTMP_ATTR",
    "MAX_ATTR",
    "MAXF_ATTR",
    "MIN_ATTR",
    "MINF_ATTR",
    "MODE_ATTR",
    "NORMAL_ATTR",
    "OBJTYP_ATTR",
    "ORPHI_ATTR",
    "ORPLO_ATTR",
    "ORPSET_ATTR",
    "ORPTNK_ATTR",
    "ORPVAL_ATTR",
    "PARENT_ATTR",
    "PERMIT_ATTR",
    "PHHI_ATTR",
    "PHLO_ATTR",
    "PHSET_ATTR",
    "PHTNK_ATTR",
    "PHVAL_ATTR",
    "PRIM_ATTR",
    "PROPNAME_ATTR",
    "PWR_ATTR",
    "QUALTY_ATTR",
    "READY_ATTR",
    "RPM_ATTR",
    "SALT_ATTR",
    "SEC_ATTR",
    "SELECT_ATTR",
    "SHOMNU_ATTR",
    "SMTSRT_ATTR",
    "SNAME_ATTR",
    "SOURCE_ATTR",
    "SPEED_ATTR",
    "STATIC_ATTR",
    "STATUS_ATTR",
    "SUBTYP_ATTR",
    "SUPER_ATTR",
    "TEMP_ATTR",
    "TIME_ATTR",
    "TIMOUT_ATTR",
    "UPDATE_ATTR",
    "USE_ATTR",
    "USER_PRIVILEGES",
    "VACFLO_ATTR",
    "VACTIM_ATTR",
    "VER_ATTR",
    "VOL_ATTR",
]

# Add discovery exports if available
if _DISCOVERY_AVAILABLE:
    __all__.extend(
        [
            "ICUnit",
            "discover_intellicenter_units",
            "find_unit_by_name",
            "find_unit_by_host",
            "DEFAULT_DISCOVERY_TIMEOUT",
        ]
    )
