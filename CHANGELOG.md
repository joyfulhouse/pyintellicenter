# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.11] - 2026-01-21

### Added

- **Cooling setpoint support** for heat pump systems (UltraTemp, etc.):
  - `get_body_cooling_setpoint(body_objnam)` - Get the cooling setpoint (temperature to cool down to)
  - `set_cooling_setpoint(body_objnam, temperature)` - Set the cooling setpoint
  - `get_body_heating_setpoint(body_objnam)` - Explicit getter for heating setpoint (alias for `get_body_setpoint`)
  - `set_heating_setpoint(body_objnam, temperature)` - Explicit setter for heating setpoint (alias for `set_setpoint`)

### Changed

- **Clarified HITMP/LOTMP attribute meanings**:
  - `HITMP` is the **cooling setpoint** (temperature to cool DOWN to)
  - `LOTMP` is the **heating setpoint** (temperature to heat UP to)
  - Updated documentation in `body.py` and `schedule.py` to reflect correct meanings

## [0.1.10] - 2026-01-14

### Changed

- **Pump mode switch handling**: `get_pump_circuit_speed()` now returns `None` when speed value is outside valid range for current mode (instead of clamping), allowing UI to show "unavailable" during mode transition

### Added

- `refresh_pump_circuit_speed(pmpcirc_objnam)` - Async method to request fresh SPEED value from IntelliCenter after mode change

## [0.1.9] - 2026-01-13

### Added

- **Pump circuit speed helpers**:
  - `get_pump_circuits()` - Get all PMPCIRC objects
  - `get_pump_circuit_speed(pmpcirc_objnam)` - Get speed clamped to valid range for current mode
  - `get_pump_circuit_mode(pmpcirc_objnam)` - Get current mode (RPM/GPM)
  - `get_pump_circuit_limits(pmpcirc_objnam)` - Get min/max limits for both modes

### Fixed

- Skip objects missing `OBJTYP` attribute instead of crashing (firmware 3.008+ compatibility)

## [0.1.8] - 2026-01-10

### Added

- **IntelliChem dosing volume attributes**:
  - `PHVOL_ATTR` - Cumulative pH chemical dosing volume in mL
  - `ORPVOL_ATTR` - Cumulative ORP chemical dosing volume in mL

## [0.1.7] - 2025-12-22

### Fixed

- **Light effect 404 error**: Fixed `set_light_effect()` returning 404 errors from IntelliCenter. The method now correctly uses `ACT` attribute (action trigger) instead of `USE` attribute (state reflection) when setting light effects.

## [0.1.6] - 2025-11-28

### Changed

- **Extracted `ICRequestMixin`**: Shared request/response correlation logic between `ICProtocol` and `ICWebSocketTransport`, reducing ~40 lines of duplicate code
- **Improved type annotations**: All getter methods now return `list[PoolObject]` instead of `list[Any]` for better IDE support and type safety
- **Added validation constants**: Chemistry controller limits are now defined as named constants (`PH_MIN`, `PH_MAX`, `ORP_MIN`, etc.) instead of magic numbers
- **Consistent timeout exceptions**: `send_request()` methods now raise `ICTimeoutError` instead of raw `TimeoutError`, with descriptive messages including command name and timeout duration

### Added

- **`ICRequestMixin`**: New mixin class in `connection.py` providing `_handle_response()`, `_next_message_id()`, `_clear_pending_request()`, and `_fail_pending_request()` methods
- **`aclose()` method**: Added async close method to `ICWebSocketTransport` for proper cleanup (awaits reader task cancellation)
- **Validation constants** in `controller.py`:
  - `PH_MIN`, `PH_MAX`, `PH_STEP` (6.0-8.5, 0.1 increments)
  - `ORP_MIN`, `ORP_MAX` (200-900 mV)
  - `CHLORINATOR_PERCENT_MIN`, `CHLORINATOR_PERCENT_MAX` (0-100)
  - `ALKALINITY_MIN`, `ALKALINITY_MAX` (0-800 ppm)
  - `CALCIUM_HARDNESS_MIN`, `CALCIUM_HARDNESS_MAX` (0-800 ppm)
  - `CYANURIC_ACID_MIN`, `CYANURIC_ACID_MAX` (0-200 ppm)

### Fixed

- **WebSocket close tracking**: `ICWebSocketTransport.close()` now tracks the async close task to avoid orphaned coroutines
- **Discovery resource leak**: Fixed potential resource leak when using external zeroconf instance - wrapper `AsyncZeroconf` is now properly closed

## [0.1.5] - 2025-11-27

### Removed

- **BREAKING**: `set_valve_state()` and `is_valve_on()` methods removed from `ICModelController`
  - Legacy valves don't have a STATUS attribute - they are automatically controlled by the system based on which body circuit (pool/spa) is active
  - These methods never worked correctly for standard valve actuators

### Added

- `get_valve_assignment(valve_objnam)` - Get the role assignment of a valve (`'INTAKE'`, `'RETURN'`, or `'NONE'`)
- `ASSIGN_ATTR` constant for valve assignment attribute

### Changed

- `VALVE_ATTRIBUTES` no longer includes `STATUS_ATTR` (legacy valves don't have this attribute)

## [0.1.4] - 2025-11-27

### Added

- **Request coalescing** for all convenience methods:
  - Multiple rapid calls are automatically batched into a single `SETPARAMLIST` request
  - "Latest value wins" semantics for conflicting updates to the same attribute
  - Reduces network round-trips and device load during rapid state changes
  - Direct API calls (`request_changes`, `send_cmd`) bypass coalescing for explicit control
  - New internal `_queue_property_change()` and `_queue_batch_changes()` methods

### Changed

- **Refactored getter methods** to use shared helpers (`_get_attr_as_int`, `_get_attr_as_float`)
  - Reduces code duplication across 12+ getter methods
  - Centralizes type conversion and error handling

## [0.1.3] - 2025-11-27

### Added

- **IntelliChem water balance configuration methods** on `ICModelController`:
  - `set_alkalinity(chem_objnam, value)` - Set alkalinity in ppm (0-800 range)
  - `set_calcium_hardness(chem_objnam, value)` - Set calcium hardness in ppm (0-800 range)
  - `set_cyanuric_acid(chem_objnam, value)` - Set cyanuric acid in ppm (0-200 range)
  - `get_alkalinity(chem_objnam)` - Get current alkalinity value
  - `get_calcium_hardness(chem_objnam)` - Get current calcium hardness value
  - `get_cyanuric_acid(chem_objnam)` - Get current cyanuric acid value
  - These are user-entered configuration values used to calculate the Saturation Index (water quality), not sensor readings

## [0.1.2] - 2025-11-27

### Added

- **Chemistry setpoint control methods** on `ICModelController`:
  - `set_ph_setpoint(chem_objnam, value)` - Set pH target (6.0-8.5 range, 0.1 increments only)
  - `set_orp_setpoint(chem_objnam, value)` - Set ORP target in mV (200-900 range)
  - `set_chlorinator_output(chem_objnam, primary_percent, secondary_percent)` - Set IntelliChlor output percentage
  - `get_ph_setpoint(chem_objnam)` - Get current pH setpoint
  - `get_orp_setpoint(chem_objnam)` - Get current ORP setpoint
  - `get_chlorinator_output(chem_objnam)` - Get chlorinator output percentages

- **Valve control methods** on `ICModelController`:
  - `set_valve_state(valve_objnam, state)` - Control valve actuators ON/OFF
  - `is_valve_on(valve_objnam)` - Check if valve is currently on

- **Vacation mode control** on `ICModelController`:
  - `set_vacation_mode(enabled)` - Enable/disable vacation mode
  - `is_vacation_mode()` - Check if vacation mode is active

- **Hardware discovery query** on `ICBaseController`:
  - `get_hardware_definition()` - Get complete panel configuration with full object hierarchy (more comprehensive than `get_configuration()`)

- **Circuit group helpers** on `ICModelController`:
  - `get_circuit_groups()` - Get all circuit group objects
  - `get_circuits_in_group(circgrp_objnam)` - Get all circuits belonging to a group
  - `circuit_group_has_color_lights(circgrp_objnam)` - Check if group contains color-capable lights
  - `get_color_light_groups()` - Get circuit groups containing color lights
  - `get_all_entities()` now includes `circuit_groups` and `color_light_groups` keys

- **Expanded attribute constants** to capture full protocol data:
  - Added `CALIB_ATTR`, `PORT_ATTR`, `PROBE_ATTR`, `SETTMP_ATTR` constants
  - BODY: Added `SETTMP` (current temp setting when body is active)
  - CHEM: Added `MODE`, `PROBE`, `READY`, `STATIC`, `TEMP` attributes
  - CIRCGRP: Added `SNAME`, `STATUS`, `USE` (light effect for groups)
  - PUMP: Added `PRIM`, `READY`, `STATIC` attributes
  - PMPCIRC: Added `READY`, `STATIC` attributes
  - SENSE: Added `CALIB` attribute
  - SCHED: Added `READY`, `UPDATE` (last modified date)
  - SYSTEM: Added `ACT3`, `ACT4`, `ENABLE`, `PERMIT`, `PORT`, `READY`, `STATIC`, `UPDATE` (firmware update flag)
  - SYSTIM: Added `CALIB`, `READY` attributes
  - PANEL, MODULE, PERMIT: Added `READY` attribute
  - PRESS, REMBTN, REMOTE, VALVE (misc): Added `READY` attribute

### Changed

- **pH setpoint validation**: `set_ph_setpoint()` now validates that values are in 0.1 increments (e.g., 7.0, 7.1, 7.2) as required by IntelliChem hardware. Invalid values like 7.05 or 7.15 are rejected with a helpful error message.

## [0.1.1] - 2025-11-27

### Changed

- **Removed deprecated `self._loop` patterns**: Transports now use `asyncio.create_task()` and `asyncio.Future()` directly instead of storing event loop references
- **Consolidated duplicate transport code**: Created `ICNotificationMixin` to share notification handling logic between `ICProtocol` and `ICWebSocketTransport` (~100 lines of code reuse)
- **Simplified controller getter methods**: All getters now delegate to `PoolModel.get_by_type()` instead of duplicating list comprehensions

### Fixed

- **Replaced bare asserts with RuntimeError**: Better error handling when notification queue is not initialized

## [0.1.0] - 2025-11-27

First stable release of pyintellicenter.

### Added

- **Dual transport support**: Both TCP and WebSocket transports
  - `ICConnection` accepts `transport` parameter: `"tcp"` (default) or `"websocket"`
  - Default ports: TCP=6681, WebSocket=6680
  - `ICWebSocketTransport` class for WebSocket connections
  - `ICTransportProtocol` interface for transport abstraction
  - `TransportType` literal type for type-safe transport selection
- **Queue-based notification processing**: Push notifications processed through async queue
  - Prevents slow callbacks from blocking the event loop
  - Bounded queue with backpressure handling (default: 100 items)
- **Home Assistant convenience helpers** on `ICModelController`:
  - Light helpers: `get_lights()`, `get_color_lights()`, `set_light_effect()`, `get_light_effect()`, `get_light_effect_name()`, `get_available_light_effects()`
  - Temperature helpers: `get_temperature_unit()`, `get_body_temperature()`, `get_body_setpoint()`, `get_body_heat_mode()`, `is_body_heating()`
  - Chemistry helpers: `get_chem_reading()`, `get_chem_alerts()`, `has_chem_alert()`
  - Sensor helpers: `get_sensors_by_type()`, `get_solar_sensors()`, `get_air_sensors()`, `get_pool_temp_sensors()`, `get_sensor_reading()`
  - Pump helpers: `is_pump_running()`, `get_pump_rpm()`, `get_pump_gpm()`, `get_pump_watts()`, `get_pump_metrics()`
  - Discovery helpers: `get_valves()`, `get_all_entities()`, `get_featured_entities()`
- **mDNS Discovery**: `discover_intellicenter_units()` with shared Zeroconf support
- **HeaterType Enum**: All 14 heater modes
- **LIGHT_EFFECTS constant**: Protocol-level mapping of color effect codes
- **Comprehensive attribute constants** for all equipment types

### Changed

- **websockets is now a required dependency** for runtime transport selection
- **Minimum Python version**: 3.13+ (aligned with Home Assistant 2025.11)

### Fixed

- WebSocket message framing with `\r\n` terminator
- Controller default port selection based on transport type
- Notification queue race condition handling

## [0.0.5a9] - 2025-11-27

### Added

- **Queue-based notification processing**: Push notifications are now processed through an async queue
  - Prevents slow callbacks from blocking the event loop
  - Bounded queue with backpressure handling (default: 100 items)
  - Graceful degradation when queue is full (drops oldest, logs warning)

- **Home Assistant convenience helpers** on `ICModelController`:
  - **Light helpers**: `get_lights()`, `get_color_lights()`, `set_light_effect()`, `get_light_effect()`, `get_light_effect_name()`, `get_available_light_effects()`
  - **Temperature helpers**: `get_temperature_unit()`, `get_body_temperature()`, `get_body_setpoint()`, `get_body_heat_mode()`, `is_body_heating()`
  - **Chemistry helpers**: `get_chem_reading()`, `get_chem_alerts()`, `has_chem_alert()`
  - **Sensor helpers**: `get_sensors_by_type()`, `get_solar_sensors()`, `get_air_sensors()`, `get_pool_temp_sensors()`, `get_sensor_reading()`
  - **Pump helpers**: `is_pump_running()`, `get_pump_rpm()`, `get_pump_gpm()`, `get_pump_watts()`, `get_pump_metrics()`
  - **Discovery helpers**: `get_valves()`, `get_all_entities()`, `get_featured_entities()`

### Changed

- **Callback type caching**: `inspect.iscoroutinefunction()` result is now cached at callback setup time
- **Efficient buffer handling**: Changed from `bytes` to `bytearray` for receive buffer (in-place operations)
- Callbacks can now be set after connection is established (consumer task starts lazily)

### Fixed

- Notification callbacks no longer block `data_received()` in the event loop

## [0.0.5a5] - 2025-11-26

### Changed

- **ICConnectionHandler.start()**: Now waits for first connection attempt before returning
  - Raises exception if first connection fails (enables proper error handling in Home Assistant)
  - Reconnection continues in background after first failure

## [0.0.5a4] - 2025-11-26

### Added

- **Shared Zeroconf support**: `discover_intellicenter_units()` now accepts optional `zeroconf` parameter to use an existing Zeroconf instance (for Home Assistant integration)

## [0.0.5a3] - 2025-11-26

### Fixed

- **Dependency compatibility**: Relax orjson requirement to >=3.10.0 for Home Assistant compatibility

## [0.0.5a2] - 2025-11-26

### Added

- **USER_PRIVILEGES export**: Now exported from main module for consistency with attributes submodule

### Removed

- **Dead code cleanup**: Removed unused `_system_object` from `PoolModel` class
- **Redundant method**: Removed `send_command()` alias method from `ICConnection` (use `send_request()` directly)

### Changed

- Code review and modernization pass confirming all async patterns are up-to-date

## [0.0.5a1] - 2025-11-26

### Added

- **LIGHT_EFFECTS constant**: Protocol-level mapping of IntelliCenter color effect codes to human-readable names
  - Codes: PARTY, CARIB, SSET, ROMAN, AMERCA, ROYAL, WHITER, REDR, BLUER, GREENR, MAGNTAR
  - Used with the `USE` attribute on lights with `COLOR_EFFECT_SUBTYPES`
  - Enables Home Assistant integrations to import effect mappings directly from the library

## [0.0.4] - 2025-11-26

### Changed

- **Zeroconf now a core dependency**: `zeroconf` moved from optional `[discovery]` extra to main dependencies
  - Install with just `pip install pyintellicenter` - no extras needed
  - Simplifies installation for Home Assistant integrations

## [0.0.3] - 2025-11-26

### Added

- **TCP Port Verification**: Discovery now verifies raw TCP port (6681) is accessible before reporting unit
- **Dual Port Support**: `ICUnit` now includes both `port` (TCP, typically 6681) and `ws_port` (WebSocket, typically 6680)
- **Live Discovery Test**: Added `scripts/test_discovery_live.py` for testing against real hardware

### Changed

- **Discovery Architecture**: Replaced deprecated event loop patterns with thread-safe asyncio.Queue
  - Sync zeroconf callbacks enqueue events
  - Async consumer processes queue and resolves services properly
  - No more "coroutine never awaited" warnings
- **Asyncio Best Practices**: Updated CLAUDE.md with guidance on proper async patterns

### Fixed

- Discovery now properly awaits async operations without storing event loop references
- TCP port calculation: mDNS advertises WebSocket port (6680), TCP port is ws_port + 1 (6681)

## [0.0.2] - 2025-11-26

### Added

- **HeaterType Enum**: New enumeration for all 14 heater modes (OFF, HEATER, SOLAR_PREF, SOLAR_ONLY, ULTRA_TEMP, ULTRA_TEMP_PREF, etc.)
- **mDNS Discovery Module** (`pyintellicenter.discovery`):
  - `ICUnit` dataclass for discovered units
  - `ICDiscoveryListener` for Zeroconf service browsing
  - `discover_intellicenter_units()` async function to find units on the network
  - `find_unit_by_name()` and `find_unit_by_host()` convenience functions
  - Optional dependency: install with `pip install pyintellicenter[discovery]`
- **Convenience Methods** on `ICModelController`:
  - `set_circuit_state(objnam, state)` - Turn circuits on/off
  - `set_heat_mode(body_objnam, mode)` - Set heater mode using HeaterType enum
  - `set_setpoint(body_objnam, temperature)` - Set temperature setpoint
  - `set_super_chlorinate(chem_objnam, enabled)` - Enable/disable super chlorination
  - `get_bodies()` - Get all pool/spa body objects
  - `get_circuits()` - Get all circuit objects
  - `get_heaters()` - Get all heater objects
  - `get_schedules()` - Get all schedule objects
  - `get_sensors()` - Get all sensor objects
- **Expanded Attribute Constants**: Added comprehensive attribute constants matching node-intellicenter:
  - Body attributes (HITMP, LOTMP, TEMP, MODE, HTSRC, HTMODE, etc.)
  - Circuit attributes (FEATR, USE, LIMIT, etc.)
  - Equipment attributes for pumps, heaters, chlorinators, chemistry
  - Schedule attributes (STIME, ETIME, TIMEBEG, TIMEEND, etc.)
  - System attributes (VER, PROPNAME, SNAME, MODE, etc.)
- **Integration Test Framework**:
  - `MockIntelliCenterServer` for testing without real hardware
  - Comprehensive integration tests for all controller classes
  - 177 total tests with 93% code coverage

### Changed

- Reorganized attributes into submodules (`attributes/body.py`, `attributes/circuit.py`, etc.)
- Improved type exports in `__init__.py`

### Fixed

- All integration tests now pass (previously 3 were skipped)

### Breaking Changes

- **BREAKING**: Minimum Python version bumped to 3.13+ (aligned with Home Assistant 2025.11)

## [0.0.1] - 2025-11-25

### Added

- Initial alpha release
- Core connection handling with `ICConnection` class
- Modern asyncio streams-based TCP communication
- Automatic keepalive with configurable interval
- `ICBaseController` for basic command handling
- `ICModelController` for maintaining equipment state model
- `ICConnectionHandler` for automatic reconnection with exponential backoff
- `PoolModel` and `PoolObject` classes for equipment state tracking
- Circuit breaker pattern for connection resilience
- Comprehensive exception hierarchy (`ICConnectionError`, `ICResponseError`, `ICCommandError`)
- Full type hints and py.typed marker
- GitHub Actions CI/CD workflows
- pytest test suite with asyncio support
- ruff linting and formatting
- mypy strict type checking

### Dependencies

- `orjson` for fast JSON serialization
- Python 3.11+ required

[Unreleased]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.11...HEAD
[0.1.11]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.10...v0.1.11
[0.1.10]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.9...v0.1.10
[0.1.9]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a13...v0.1.0
[0.0.5a13]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a12...v0.0.5a13
[0.0.5a12]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a11...v0.0.5a12
[0.0.5a11]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a10...v0.0.5a11
[0.0.5a10]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a9...v0.0.5a10
[0.0.5a9]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a8...v0.0.5a9
[0.0.5a5]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a4...v0.0.5a5
[0.0.5a4]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a3...v0.0.5a4
[0.0.5a3]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a2...v0.0.5a3
[0.0.5a2]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a1...v0.0.5a2
[0.0.5a1]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.4...v0.0.5a1
[0.0.4]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/joyfulhouse/pyintellicenter/releases/tag/v0.0.1
