# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.1.2...HEAD
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
