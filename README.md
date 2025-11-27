# pyintellicenter

[![PyPI version](https://badge.fury.io/py/pyintellicenter.svg)](https://pypi.org/project/pyintellicenter/)
[![Python Versions](https://img.shields.io/pypi/pyversions/pyintellicenter.svg)](https://pypi.org/project/pyintellicenter/)
[![Tests](https://github.com/joyfulhouse/pyintellicenter/actions/workflows/test.yml/badge.svg)](https://github.com/joyfulhouse/pyintellicenter/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Python library for communicating with Pentair IntelliCenter pool control systems over local network.

> **Alpha Release**: This library is in early development. API may change between versions.

## Features

- **Dual Transport Support**: TCP (port 6681) and WebSocket (port 6680) connections
- **Local Communication**: Direct connection to IntelliCenter (no cloud required)
- **Real-time Updates**: Push-based notifications via NotifyList protocol
- **mDNS Discovery**: Automatically find IntelliCenter units on your network
- **Async/Await**: Built on Python asyncio for efficient I/O
- **Type Annotations**: Full type hints for IDE support and static analysis
- **Robust Connection Handling**: Automatic reconnection with exponential backoff
- **Circuit Breaker Pattern**: Prevents connection storms during outages
- **Home Assistant Ready**: Convenience helpers for integration development

## Installation

```bash
pip install pyintellicenter
```

## Requirements

- Python 3.13+
- Pentair IntelliCenter controller (i5P, i8P, i10P, or similar)
- Local network access to IntelliCenter

## Quick Start

### Basic Connection (TCP)

```python
import asyncio
from pyintellicenter import ICModelController, PoolModel, ICConnectionHandler

async def main():
    # Create a model to hold equipment state
    model = PoolModel()

    # Create controller connected to your IntelliCenter
    controller = ICModelController("192.168.1.100", model)

    # Use ICConnectionHandler for automatic reconnection
    handler = ICConnectionHandler(controller)
    await handler.start()

    # Access system information
    print(f"Connected to: {controller.system_info.prop_name}")
    print(f"Software version: {controller.system_info.sw_version}")

    # List all equipment
    for obj in model:
        print(f"{obj.sname} ({obj.objtype}): {obj.status}")

    # Control equipment - turn on pool
    await controller.set_circuit_state("POOL", True)

    # Clean shutdown
    await handler.stop()

asyncio.run(main())
```

### WebSocket Connection

```python
from pyintellicenter import ICConnection

async def main():
    # Use WebSocket transport instead of TCP
    async with ICConnection("192.168.1.100", transport="websocket") as conn:
        response = await conn.send_request(
            "GetParamList",
            condition="",
            objectList=[{"objnam": "INCR", "keys": ["VER", "SNAME"]}]
        )
        print(response)

asyncio.run(main())
```

### Auto-Discovery

```python
from pyintellicenter import discover_intellicenter_units

async def main():
    # Find all IntelliCenter units on the network
    units = await discover_intellicenter_units(timeout=5.0)

    for unit in units:
        print(f"Found: {unit.name} at {unit.host}:{unit.port}")
        print(f"  Model: {unit.model}")
        print(f"  WebSocket port: {unit.ws_port}")

asyncio.run(main())
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    ICConnectionHandler                   │
│              (Auto-reconnection, callbacks)              │
├─────────────────────────────────────────────────────────┤
│                    ICModelController                     │
│           (State management, helper methods)             │
├─────────────────────────────────────────────────────────┤
│                     ICBaseController                     │
│              (Command handling, metrics)                 │
├─────────────────────────────────────────────────────────┤
│                      ICConnection                        │
│               (Transport selection, flow control)        │
├──────────────────────┬──────────────────────────────────┤
│      ICProtocol      │       ICWebSocketTransport       │
│    (TCP transport)   │      (WebSocket transport)       │
└──────────────────────┴──────────────────────────────────┘
```

### Layer Overview

| Layer | Class | Purpose |
|-------|-------|---------|
| Handler | `ICConnectionHandler` | Auto-reconnection, lifecycle callbacks |
| Controller | `ICModelController` | State management, convenience methods |
| Controller | `ICBaseController` | Basic command handling, metrics |
| Connection | `ICConnection` | Transport selection, request flow control |
| Transport | `ICProtocol` | TCP communication (port 6681) |
| Transport | `ICWebSocketTransport` | WebSocket communication (port 6680) |
| Model | `PoolModel` | Equipment collection |
| Model | `PoolObject` | Individual equipment item |

## API Reference

### ICConnection

Low-level connection wrapper supporting both TCP and WebSocket transports.

```python
from pyintellicenter import ICConnection

# TCP connection (default)
conn = ICConnection("192.168.1.100")
conn = ICConnection("192.168.1.100", transport="tcp")
conn = ICConnection("192.168.1.100", port=6681)

# WebSocket connection
conn = ICConnection("192.168.1.100", transport="websocket")
conn = ICConnection("192.168.1.100", port=6680, transport="websocket")

# Full configuration
conn = ICConnection(
    host="192.168.1.100",
    port=6681,                    # Default: 6681 (TCP), 6680 (WebSocket)
    transport="tcp",              # "tcp" or "websocket"
    response_timeout=30.0,        # Request timeout in seconds
    keepalive_interval=90.0,      # Keepalive interval in seconds
    notification_queue_size=100,  # Max queued notifications
)

# Usage as context manager
async with ICConnection("192.168.1.100") as conn:
    response = await conn.send_request("GetParamList", ...)

# Manual connection management
await conn.connect()
response = await conn.send_request("GetParamList", ...)
await conn.disconnect()

# Callbacks
conn.set_notification_callback(lambda msg: print(msg))
conn.set_disconnect_callback(lambda exc: print(f"Disconnected: {exc}"))
```

### ICModelController

Controller that maintains equipment state in a PoolModel.

```python
from pyintellicenter import ICModelController, PoolModel

model = PoolModel()
controller = ICModelController(
    host="192.168.1.100",
    model=model,
    port=6681,
    keepalive_interval=90.0,
)

await controller.start()

# System information
info = controller.system_info
print(f"Name: {info.prop_name}")
print(f"Version: {info.sw_version}")
print(f"Unique ID: {info.unique_id}")
print(f"Uses Metric: {info.uses_metric}")

# Equipment control
await controller.set_circuit_state("POOL", True)
await controller.set_circuit_state("SPA", False)
await controller.set_heat_mode("B1101", HeaterType.HEATER)
await controller.set_setpoint("B1101", 84)
await controller.set_super_chlorinate("C0001", True)
await controller.set_light_effect("C0003", "PARTY")

# Batch operations
await controller.set_multiple_circuit_states(["AUX1", "AUX2"], True)

# Entity getters
bodies = controller.get_bodies()
circuits = controller.get_circuits()
pumps = controller.get_pumps()
heaters = controller.get_heaters()
sensors = controller.get_sensors()
schedules = controller.get_schedules()
lights = controller.get_lights()
color_lights = controller.get_color_lights()
chem_controllers = controller.get_chem_controllers()
valves = controller.get_valves()

# All entities grouped by type (for Home Assistant discovery)
entities = controller.get_all_entities()
# Returns: {"bodies": [...], "circuits": [...], "lights": [...], ...}

# Temperature helpers
unit = controller.get_temperature_unit()  # "F" or "C"
temp = controller.get_body_temperature("B1101")
setpoint = controller.get_body_setpoint("B1101")
heat_mode = controller.get_body_heat_mode("B1101")
is_heating = controller.is_body_heating("B1101")

# Chemistry helpers
ph = controller.get_chem_reading("C0001", "PH")
orp = controller.get_chem_reading("C0001", "ORP")
salt = controller.get_chem_reading("C0001", "SALT")
alerts = controller.get_chem_alerts("C0001")

# Pump helpers
is_running = controller.is_pump_running("P0001")
rpm = controller.get_pump_rpm("P0001")
gpm = controller.get_pump_gpm("P0001")
watts = controller.get_pump_watts("P0001")
metrics = controller.get_pump_metrics("P0001")  # {"rpm": ..., "gpm": ..., "watts": ...}

# Sensor helpers
air_sensors = controller.get_air_sensors()
solar_sensors = controller.get_solar_sensors()
reading = controller.get_sensor_reading("S0001")

# Light helpers
effect = controller.get_light_effect("C0003")
effect_name = controller.get_light_effect_name("C0003")
available = controller.get_available_light_effects("C0003")

# Update callback
def on_update(controller, changes):
    for objnam, attrs in changes.items():
        print(f"{objnam} changed: {attrs}")

controller.set_updated_callback(on_update)

await controller.stop()
```

### ICConnectionHandler

Wraps a controller with automatic reconnection and lifecycle callbacks.

```python
from pyintellicenter import ICConnectionHandler, ICConnectionHandlerCallbacks

callbacks = ICConnectionHandlerCallbacks(
    on_started=lambda: print("Connected!"),
    on_stopped=lambda: print("Stopped"),
    on_disconnected=lambda: print("Disconnected"),
    on_reconnected=lambda: print("Reconnected!"),
    on_retrying=lambda attempt, delay: print(f"Retry {attempt} in {delay}s"),
)

handler = ICConnectionHandler(
    controller,
    callbacks=callbacks,
    time_between_reconnects=30.0,    # Initial reconnect delay
    disconnect_debounce_time=15.0,   # Grace period before disconnect callback
)

# Start connection (waits for first connection)
await handler.start()

# Access the underlying controller
print(handler.controller.system_info.prop_name)

# Check connection state
print(f"Connected: {handler.connected}")

# Stop with cleanup
await handler.stop()
```

### PoolModel

Collection of pool equipment objects.

```python
from pyintellicenter import PoolModel

model = PoolModel()

# Iteration
for obj in model:
    print(f"{obj.objnam}: {obj.sname}")

# Access by object name
pump = model["PUMP1"]

# Get objects by type
bodies = model.get_by_type("BODY")
pools = model.get_by_type("BODY", "POOL")
pumps = model.get_by_type("PUMP")

# Get children of an object
children = model.get_children(panel)

# Object count
print(f"Total objects: {model.num_objects}")
```

### PoolObject

Individual equipment item.

```python
obj = model["PUMP1"]

# Core properties
obj.objnam     # Object name: "PUMP1"
obj.sname      # Friendly name: "Pool Pump"
obj.objtype    # Type: "PUMP"
obj.subtype    # Subtype: "VSF"
obj.status     # Status: "ON" or "OFF"
obj.parent     # Parent object name

# Type checks
obj.is_a_light              # Is this a light?
obj.is_a_light_show         # Is this a light show circuit?
obj.is_featured             # Is this marked as featured?
obj.supports_color_effects  # Supports IntelliBrite effects?
obj.is_on                   # Is status ON?

# Attribute access
rpm = obj["RPM"]
power = obj["PWR"]
temp = obj["TEMP"]

# All attributes
for key in obj.attribute_keys:
    print(f"{key}: {obj[key]}")
```

### Discovery

Find IntelliCenter units on your local network using mDNS/Zeroconf.

```python
from pyintellicenter import (
    discover_intellicenter_units,
    find_unit_by_name,
    find_unit_by_host,
    ICUnit,
)

# Discover all units
units = await discover_intellicenter_units(timeout=5.0)

# With existing Zeroconf instance (for Home Assistant)
from zeroconf import Zeroconf
zc = Zeroconf()
units = await discover_intellicenter_units(timeout=5.0, zeroconf=zc)

# Find specific unit
unit = await find_unit_by_name("My Pool", timeout=5.0)
unit = await find_unit_by_host("192.168.1.100", timeout=5.0)

# ICUnit properties
unit.name      # Friendly name
unit.host      # IP address
unit.port      # TCP port (6681)
unit.ws_port   # WebSocket port (6680)
unit.model     # Model info (if available)
```

## Equipment Types

| Type | Constant | Description | Common Subtypes |
|------|----------|-------------|-----------------|
| Body | `BODY_TYPE` | Body of water | `POOL`, `SPA` |
| Pump | `PUMP_TYPE` | Variable speed pump | `SPEED`, `FLOW`, `VSF` |
| Circuit | `CIRCUIT_TYPE` | Circuit/Feature | `GENERIC`, `LIGHT`, `INTELLI`, `GLOW`, `DIMMER` |
| Heater | `HEATER_TYPE` | Heater | `GENERIC`, `SOLAR`, `ULTRA`, `HYBRID` |
| Chem | `CHEM_TYPE` | Chemistry controller | `ICHLOR`, `ICHEM` |
| Sensor | `SENSE_TYPE` | Temperature sensor | `POOL`, `AIR`, `SOLAR` |
| Schedule | `SCHED_TYPE` | Schedule | - |
| Valve | `VALVE_TYPE` | Valve | - |

## Heater Modes

```python
from pyintellicenter import HeaterType

HeaterType.OFF              # Heater off
HeaterType.HEATER           # Gas/electric heater only
HeaterType.SOLAR_PREF       # Solar preferred, heater backup
HeaterType.SOLAR_ONLY       # Solar only
HeaterType.ULTRA_TEMP       # UltraTemp heat pump only
HeaterType.ULTRA_TEMP_PREF  # UltraTemp preferred
HeaterType.HYBRID           # Hybrid mode
# ... and more
```

## Light Effects

```python
from pyintellicenter import LIGHT_EFFECTS

# Available effects for IntelliBrite/MagicStream lights
LIGHT_EFFECTS = {
    "PARTY": "Party",
    "ROMAN": "Romance",
    "CARIB": "Caribbean",
    "AMERCA": "American",
    "SSET": "Sunset",
    "ROYAL": "Royalty",
    "BLUER": "Blue",
    "GREENR": "Green",
    "REDR": "Red",
    "WHITER": "White",
    "MAGNTAR": "Magenta",
}

# Set light effect
await controller.set_light_effect("C0003", "PARTY")
```

## Connection Behavior

### Connection Flow

1. **Connect**: Establishes TCP or WebSocket connection
2. **Initialize**: Fetches system info and all equipment objects
3. **Monitor**: Receives real-time NotifyList push updates
4. **Keepalive**: Sends queries every 90 seconds (configurable)

### Reconnection Strategy

1. **Debounce**: 15-second grace period before marking disconnected
2. **Exponential Backoff**: Starts at 30s, doubles each attempt (max 5 min)
3. **Circuit Breaker**: After 5 consecutive failures, pauses for 5 minutes
4. **Reset**: Successful connection resets failure counters

### Notification Processing

- Push notifications are queued (default: 100 items max)
- Queue prevents slow callbacks from blocking I/O
- When full, oldest notifications are dropped (prefers fresh state)
- Both sync and async callbacks are supported

## Error Handling

```python
from pyintellicenter import (
    ICError,           # Base exception
    ICConnectionError, # Connection failures
    ICResponseError,   # Bad response from IntelliCenter
    ICCommandError,    # Command execution error
    ICTimeoutError,    # Request timeout
)

try:
    await controller.start()
except ICConnectionError as e:
    print(f"Connection failed: {e}")
except ICTimeoutError as e:
    print(f"Request timed out: {e}")
```

## Development

```bash
# Clone repository
git clone https://github.com/joyfulhouse/pyintellicenter.git
cd pyintellicenter

# Install with uv (recommended)
uv sync --extra dev

# Run tests
uv run pytest tests/

# Run tests with coverage
uv run pytest tests/ --cov=src/pyintellicenter --cov-report=term-missing

# Linting and formatting
uv run ruff check .
uv run ruff format .

# Type checking
uv run mypy src/pyintellicenter

# Full validation
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/pyintellicenter && uv run pytest tests/
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Related Projects

- [intellicenter](https://github.com/joyfulhouse/intellicenter) - Home Assistant integration using this library
- [node-intellicenter](https://github.com/pent-house/node-intellicenter) - Node.js library (protocol reference)
