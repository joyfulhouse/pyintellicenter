# pyintellicenter

[![PyPI version](https://badge.fury.io/py/pyintellicenter.svg)](https://pypi.org/project/pyintellicenter/)
[![Python Versions](https://img.shields.io/pypi/pyversions/pyintellicenter.svg)](https://pypi.org/project/pyintellicenter/)
[![Tests](https://github.com/joyfulhouse/pyintellicenter/actions/workflows/test.yml/badge.svg)](https://github.com/joyfulhouse/pyintellicenter/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Python library for communicating with Pentair IntelliCenter pool control systems over local network.

> ⚠️ **Alpha Release**: This library is in early development. API may change between versions.

## Features

- **Local Communication**: Direct TCP connection to IntelliCenter (no cloud required)
- **Real-time Updates**: Push-based notifications via NotifyList protocol
- **Async/Await**: Built on Python asyncio for efficient I/O
- **Type Annotations**: Full type hints for IDE support and static analysis
- **Robust Connection Handling**: Automatic reconnection with exponential backoff
- **Resilient**: Circuit breaker pattern, connection metrics, comprehensive error handling

## Installation

```bash
pip install pyintellicenter
```

Or install from GitHub:

```bash
pip install git+https://github.com/joyfulhouse/pyintellicenter.git
```

## Requirements

- Python 3.11+
- Pentair IntelliCenter controller (i5P, i7P, i9P, or i10P)
- Local network access to IntelliCenter (TCP port 6681)

## Quick Start

```python
import asyncio
from pyintellicenter import ModelController, PoolModel, ConnectionHandler

async def main():
    # Create a model to hold equipment state
    model = PoolModel()

    # Create controller connected to your IntelliCenter
    controller = ModelController("192.168.1.100", model)

    # Use ConnectionHandler for automatic reconnection
    handler = ConnectionHandler(controller)
    await handler.start()

    # Access system information
    print(f"Connected to: {controller.systemInfo.propName}")
    print(f"Software version: {controller.systemInfo.swVersion}")

    # List all equipment
    for obj in model:
        print(f"{obj.sname} ({obj.objtype}): {obj.status}")

    # Control equipment
    pool = model.getByType("BODY", "POOL")[0]
    controller.requestChanges(pool.objnam, {"STATUS": "ON"})

asyncio.run(main())
```

## Architecture

The library is organized in layers:

### Protocol Layer (`protocol.py`)
- `ICProtocol`: Low-level asyncio protocol handling TCP communication
- JSON message framing (messages terminated with `\r\n`)
- Flow control (one request at a time)
- Keepalive queries for connection health

### Controller Layer (`controller.py`)
- `BaseController`: Basic connection and command handling
- `ModelController`: State management with PoolModel
- `ConnectionHandler`: Automatic reconnection with exponential backoff
- `SystemInfo`: System metadata (version, units, unique ID)
- `ConnectionMetrics`: Request/response statistics

### Model Layer (`model.py`)
- `PoolModel`: Collection of pool equipment objects
- `PoolObject`: Individual equipment item (pump, light, heater, etc.)

### Attributes (`attributes.py`)
- Type and attribute constants for all equipment types
- `BODY_TYPE`, `PUMP_TYPE`, `CIRCUIT_TYPE`, etc.
- `STATUS_ATTR`, `SNAME_ATTR`, `OBJTYP_ATTR`, etc.

## API Reference

### ModelController

```python
controller = ModelController(
    host="192.168.1.100",  # IntelliCenter IP address
    model=PoolModel(),     # Model to populate
    port=6681,             # TCP port (default: 6681)
    keepalive_interval=90, # Keepalive query interval in seconds
)

# Start connection and populate model
await controller.start()

# Send changes to equipment
controller.requestChanges(objnam, {"STATUS": "ON"})

# Access system info
info = controller.systemInfo
print(info.propName, info.swVersion, info.usesMetric)
```

### ConnectionHandler

```python
handler = ConnectionHandler(
    controller,
    timeBetweenReconnects=30,    # Initial reconnect delay (seconds)
    disconnectDebounceTime=15,   # Grace period before marking disconnected
)

# Start with automatic reconnection
await handler.start()

# Stop and cleanup
handler.stop()
```

### PoolModel

```python
model = PoolModel()

# Iterate all objects
for obj in model:
    print(obj.sname)

# Get by type
bodies = model.getByType("BODY")
pool = model.getByType("BODY", "POOL")[0]
pumps = model.getByType("PUMP")

# Get by object name
obj = model["POOL1"]

# Get children of an object
children = model.getChildren(panel)
```

### PoolObject

```python
obj = model["PUMP1"]

# Properties
obj.objnam    # Object name (e.g., "PUMP1")
obj.sname     # Friendly name (e.g., "Pool Pump")
obj.objtype   # Object type (e.g., "PUMP")
obj.subtype   # Subtype (e.g., "VSF")
obj.status    # Current status

# Check type
obj.isALight           # Is this a light?
obj.isALightShow       # Is this a light show?
obj.isFeatured         # Is this featured?
obj.supportColorEffects # Supports color effects?

# Access attributes
rpm = obj["RPM"]
power = obj["PWR"]
```

## Equipment Types

| Type | Description | Common Subtypes |
|------|-------------|-----------------|
| `BODY` | Body of water | `POOL`, `SPA` |
| `PUMP` | Pump | `SPEED`, `FLOW`, `VSF` |
| `CIRCUIT` | Circuit/Feature | `LIGHT`, `INTELLI`, `GLOW`, `DIMMER` |
| `HEATER` | Heater | `GENERIC`, `SOLAR`, `ULTRA` |
| `CHEM` | Chemistry | `ICHLOR`, `ICHEM` |
| `SENSE` | Sensor | `POOL`, `AIR`, `SOLAR` |
| `SCHED` | Schedule | - |

## Connection Behavior

The library implements robust connection handling:

1. **Initial Connection**: Connects and fetches system info + all equipment
2. **Keepalive**: Sends lightweight queries every 90 seconds (configurable)
3. **Push Updates**: Receives real-time NotifyList updates from IntelliCenter
4. **Reconnection**: Exponential backoff starting at 30 seconds (configurable)
5. **Circuit Breaker**: Pauses after 5 consecutive failures

## Development

```bash
# Clone repository
git clone https://github.com/joyfulhouse/pyintellicenter.git
cd pyintellicenter

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check src tests
ruff format src tests

# Run type checking
mypy src
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Related Projects

- [intellicenter](https://github.com/joyfulhouse/intellicenter) - Home Assistant integration using this library
