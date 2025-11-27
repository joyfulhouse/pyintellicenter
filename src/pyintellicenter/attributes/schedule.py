"""Schedule attribute definitions."""

from .constants import (
    ACT_ATTR,
    AVAIL_ATTR,
    CIRCUIT_ATTR,
    COOLING_ATTR,
    GROUP_ATTR,
    HEATER_ATTR,
    HNAME_ATTR,
    LISTORD_ATTR,
    LOTMP_ATTR,
    MODE_ATTR,
    READY_ATTR,
    SMTSRT_ATTR,
    SNAME_ATTR,
    STATIC_ATTR,
    STATUS_ATTR,
    TIME_ATTR,
    TIMOUT_ATTR,
    UPDATE_ATTR,
    VACFLO_ATTR,
    VACTIM_ATTR,
)

# Schedule attributes
# Matches node-intellicenter GetSchedule attributes
SCHED_ATTRIBUTES = {
    ACT_ATTR,  # (ON/OFF) ON if schedule is currently active
    AVAIL_ATTR,  # Availability status
    CIRCUIT_ATTR,  # (objnam) The circuit controlled by this schedule
    COOLING_ATTR,  # (ON/OFF) Cooling mode for this schedule
    "DAY",  # Days this schedule runs (e.g., 'MTWRFAU' for every day, 'AU' for weekends)
    "DNTSTP",  # (ON/OFF) Don't Stop - Set to ON to never end
    GROUP_ATTR,  # Schedule group
    HEATER_ATTR,  # Set to HEATER objnam if schedule should trigger heating
    # '00000' for off, '00001' for Don't Change
    "HITMP",  # (int) High temperature setting
    HNAME_ATTR,  # Same as objnam
    LISTORD_ATTR,  # (int) Used to order in UI
    LOTMP_ATTR,  # (int) When heater is set, this is the desired temperature
    MODE_ATTR,  # (str) Schedule mode
    READY_ATTR,  # (ON/OFF) Ready state
    "SINGLE",  # (ON/OFF) ON if the schedule should not repeat
    SMTSRT_ATTR,  # Smart start setting
    SNAME_ATTR,  # Friendly name of the schedule
    "START",  # Start time mode: 'ABSTIM' (absolute), 'SRIS' (sunrise), 'SSET' (sunset)
    STATIC_ATTR,  # (ON/OFF) Static setting
    STATUS_ATTR,  # (ON/OFF) ON if schedule is active
    "STOP",  # Stop time mode: 'ABSTIME', 'SRIS', or 'SSET'
    TIME_ATTR,  # Time the schedule starts in 'HH,MM,SS' format (24h clock)
    TIMOUT_ATTR,  # Time the schedule stops in 'HH,MM,SS' format (24h clock)
    UPDATE_ATTR,  # Last update timestamp
    VACFLO_ATTR,  # (ON/OFF) ON if schedule only applies to Vacation Mode
    VACTIM_ATTR,  # Vacation time setting
}
