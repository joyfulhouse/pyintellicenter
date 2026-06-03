# Architecture

How pyintellicenter is structured and why.

## Overview

`pyintellicenter` is a layered async Python library for communicating with Pentair
IntelliCenter pool controllers. The library separates transport concerns, protocol
framing, state management, and reconnection logic into discrete layers so each can
be tested and evolved independently.

## Components

```
+----------------------------------------------------------+
|                    ICConnectionHandler                    |
|              (Auto-reconnection, callbacks)               |
+----------------------------------------------------------+
|                    ICModelController                      |
|           (State management, helper methods)              |
+----------------------------------------------------------+
|                     ICBaseController                      |
|              (Command handling, metrics)                  |
+----------------------------------------------------------+
|                      ICConnection                         |
|               (Transport selection, flow control)         |
+----------------------+-----------------------------------+
|      ICProtocol      |       ICWebSocketTransport        |
|    (TCP transport)   |      (WebSocket transport)        |
+----------------------+-----------------------------------+
```

| Layer | Class | Responsibility |
|-------|-------|----------------|
| Handler | `ICConnectionHandler` | Lifecycle management, exponential backoff reconnection, circuit breaker |
| Controller | `ICModelController` | Equipment state model, all domain-specific convenience helpers |
| Controller | `ICBaseController` | Raw command send/receive, request metrics |
| Connection | `ICConnection` | Transport selection (TCP vs WebSocket), request queuing, flow control |
| Transport | `ICProtocol` | asyncio Protocol implementation for TCP (port 6681) |
| Transport | `ICWebSocketTransport` | WebSocket framing over `websockets` (port 6680) |
| Model | `PoolModel` | Ordered collection of all `PoolObject` instances |
| Model | `PoolObject` | Single equipment item with typed attribute access |

## Data Flow

**Initialization:**

1. `ICConnection.connect()` establishes the transport layer.
2. `ICBaseController` sends `GetParamList` to fetch system info and all equipment
   objects.
3. `PoolModel` is populated; `ICModelController` subscribes to `NotifyList` for all
   tracked object names.

**Real-time updates:**

1. IntelliCenter pushes `NotifyList` messages whenever equipment state changes.
2. The transport layer places each message on an async notification queue (max 100).
3. A consumer coroutine drains the queue and calls `PoolModel.process_updates()`.
4. The registered `on_updated` callback is invoked with the set of changed objects.

**Commands:**

1. Convenience methods on `ICModelController` queue a `_queue_property_change()`.
2. A coalescing flush sends a single `SETPARAMLIST` for all pending changes.
3. Responses are correlated by message ID and returned to the awaiting caller.

## Key Design Decisions

- **Dual transport via strategy pattern**: `ICConnection` holds a `ICTransportProtocol`
  instance rather than inheriting from either transport, so TCP and WebSocket can be
  swapped transparently.
- **Queue-based notification processing**: Decouples slow user callbacks from the asyncio
  event loop; oldest items are dropped when the queue fills (fresh state wins).
- **Request coalescing**: Rapid calls to setter helpers are batched into one
  `SETPARAMLIST` to reduce device load.
- **Circuit breaker on reconnect**: Prevents a flood of reconnect attempts from
  overwhelming a controller that is rebooting or unreachable.
- **`TYPE_CHECKING`-only mixin base**: Domain mixins use a non-abstract stub so that
  downstream type-checkers (mypy, pyright) can resolve `ICModelController` as fully
  concrete without a `follow_imports = skip` boundary.
