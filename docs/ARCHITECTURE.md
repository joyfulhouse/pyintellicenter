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

### Authoritative telemetry reconciliation

Firmware may notify only the first subscribed alias of shared device storage:
reporting that alias updates a per-client snapshot before later aliases compare
against it. A healthy connection therefore cannot establish freshness for all
telemetry. See the [issue #212 RCA](https://github.com/joyfulhouse/intellicenter/issues/212#issuecomment-6422806614).
AIR SOURCE/PROBE suppression was reproduced on physical 1.064 hardware; the
snapshot algorithm also exists in 3.014. Water/body aliasing has firmware and
production evidence, but the reverse water/body order still needs hardware tests.

`ICModelController` owns one default-on worker shared by TCP and WebSocket. It
rebuilds targets each tick from tracked attributes and current object types:
all SENSE SOURCE/PROBE, BODY TEMP/LSTTMP, and ICHLOR SALT (excluding ICHEM).
LSTTMP is independent storage, not an alias claim. SOLAR inclusion is inferred.
Salt reads are defensive; the salt staleness cause is **UNVERIFIED**.

The keyword-only `telemetry_reconcile_interval` defaults to 60 seconds, accepts
finite values in [30, 900], and accepts `None` to disable. Startup already reads
the snapshot, so the worker waits one interval before its first read. Each tick
sends at most one GetParamList with at most 50 pairs and one entry per object;
two-key targets precede single-key targets so full batches rotate fairly without
splitting objects. While reads succeed, inventories of at most 50 target pairs
are fully read every completed reconciliation tick. Larger inventories with
stable membership and tracked keys are covered within
`R = ceil(target_pairs / 50)` completed ticks; after the final target-set change,
within `2 * R` completed ticks using the settled pair count. Continuous churn has
no finite coverage bound.

For multi-tick inventories, stable sort keys and `bisect_right` resume after the
last-read object even when earlier objects disappear. Completing a rotation
clears the cursor, so later insertions cannot prevent the next wrap. A target-set
change can place an affected target behind the cursor and defer it to the next
rotation. The remaining rotation and one full rotation give the `2 * R` tick
bound after changes stop. Single-batch inventories ignore any continuation from
an older, larger inventory.

Ticks are scheduled every `interval` (60 seconds by default); overrunning a slot
skips missed ticks without bursts. Without scheduling delays, a tick taking `d`
seconds occupies
`max(1, floor(d / interval) + 1)` interval slots before the next start:
`ceil(d / interval)` slots unless completion lands exactly on a boundary, when
one more slot is skipped. Here `d` includes the request and local processing;
scheduling delays add elapsed time. Request duration includes queueing, write
and response, bounded by the existing total deadline
(`ICConnection.__init__`: `request_total_timeout=60.0` seconds by default).

Failures double the next delay up to 900 seconds, reset on success;
known queued-but-unsent timeouts do not grow backoff.
No outer timeout cancels an in-flight transport request; existing request
deadlines and metrics apply. A reconciliation request shares the connection
request lock, so it can delay queued user commands by at most the existing
response deadline. The first expected failure logs a warning and the first
unexpected error logs a traceback, even after a known failure. Repeated failures
and recovery log at debug level; success resets both logging gates.

The worker captures the connection, receipt generation and PoolObject identities.
After awaiting the response it rejects obsolete state and accepts only requested
pairs. A batch-local dirty set records any requested pair observed through
`_apply_updates` while the read is in flight, even if that observation repeats
the current value; those pairs are dropped. A notification still queued at apply
time applies later and wins by last write. A push queued before the request can
therefore temporarily overwrite a fresher readback until that field's next
reconciliation read, subject to the same inventory bounds. This is an accepted
limitation. No permanent per-field revision counters exist.

Readbacks are coalesced to one entry per object and synchronously applied through
`self._apply_updates`, preserving receipts, subscribers, legacy callbacks and HA
subclass hooks. SOURCE and PROBE are never copied into each other or body TEMP;
no calibration arithmetic is performed. Stop and restart cancel and await the
worker before disconnecting/replacing connection state; failed setup spawns none.
Loopback TCP/WebSocket tests and synthetic alias fakes validate this software
contract. Unit tests are not physical firmware validation; no new hardware
validation or firmware-fix claim accompanies this change.

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
