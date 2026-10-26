# Troubleshooting

Common problems with pyintellicenter and how to resolve them.

## Common Issues

### Temperature or salt stays stale on a healthy connection

Firmware can suppress notifications for later aliases of shared temperature
storage after notifying the first subscribed alias. Changing subscription order
changes the winner and does not resolve the defect. See the
[issue #212 RCA](https://github.com/joyfulhouse/intellicenter/issues/212#issuecomment-6422806614).
Reloading recovers a snapshot temporarily; firmware 3.014 is not established as
a fix. Salt staleness has a separate **UNVERIFIED** cause: its inclusion is
defensive. SOLAR reconciliation is inferred, not validated alias behavior.

`ICModelController` now reconciles tracked SENSE SOURCE/PROBE, BODY TEMP/LSTTMP
and ICHLOR SALT through independent authoritative reads. LSTTMP is separate
storage, and ICHEM is excluded. The default 60-second interval can be configured
with the keyword-only `telemetry_reconcile_interval` (finite 30-900 seconds), or
disabled with `None`. At most one request and 50 pairs are read per tick. While
reads succeed, inventories of at most 50 target pairs are fully read every
completed reconciliation tick. Larger inventories with stable membership and
tracked keys are covered within `R = ceil(target_pairs / 50)` completed ticks;
after the final target-set change, within `2 * R` completed ticks using the
settled pair count. Continuous churn has no finite coverage bound.

Ticks are scheduled every `interval` (60 seconds by default); overrunning a slot
skips missed ticks without bursts. Without scheduling delays, a tick taking `d`
seconds occupies
`max(1, floor(d / interval) + 1)` interval slots before the next start:
`ceil(d / interval)` slots unless completion lands exactly on a boundary, when
one more slot is skipped. Here `d` includes the request and local processing;
scheduling delays add elapsed time. Request duration includes queueing, write
and response, bounded by the existing total deadline
(`ICConnection.__init__`: `request_total_timeout=60.0` seconds by default).

Failures back off to at most 900 seconds. Queued-but-unsent timeouts do not
increase backoff. Startup waits one interval before its first scheduled read,
and stop awaits cancellation.

Check debug logs for reconciliation failures/recovery and use `field_receipt()`
to distinguish local field ingestion from value changes. An unchanged read can
refresh its receipt without firing a callback. Readbacks never synthesize
temperatures or copy SOURCE into PROBE/body TEMP. An old salt timestamp alone
does not establish a mismatch; compare a direct SALT read with the cached value.
Tests exercise synthetic aliases and loopback TCP/WebSocket recovery; unit tests
are not physical firmware validation. Water/body order reversal and physical
3.014 verification remain hardware follow-up work.

### Connection refused / timeout

**Symptom:** `ICConnectionError` immediately on `handler.start()`.

**Cause:** The controller IP or port is wrong, or the host is unreachable.

**Fix:** Verify the IP address with `ping` or your router's DHCP lease table.
Confirm port 6681 (TCP) or 6680 (WebSocket) is reachable:
```bash
nc -zv 192.168.1.100 6681
```

### Immediate disconnect after connecting

**Symptom:** `on_disconnected` fires seconds after `on_started`.

**Cause:** Another client (the IntelliCenter app or a competing integration) may
be holding the single TCP slot.

**Fix:** Disconnect other clients and retry. The library will automatically
reconnect with exponential backoff.

### Equipment not appearing in model

**Symptom:** `controller.get_bodies()` or similar returns an empty list.

**Cause:** The initial `GetParamList` fetch may have timed out, or the
controller firmware version does not expose that equipment type.

**Fix:** Enable debug logging (see below) to inspect the raw `GetParamList`
response.

### Light effect returns 404

**Symptom:** Calling `set_light_effect()` logs a 404 response from IntelliCenter.

**Cause:** Using the `USE` attribute directly instead of the `ACT` action trigger.
This was a regression fixed in v0.1.15.

**Fix:** Upgrade to v0.1.15 or later.

### mypy reports ICModelController as abstract

**Symptom:** Downstream code fails type checking with `[abstract]` on
`ICModelController(...)`.

**Cause:** The domain mixin protocol was inadvertently abstract before v0.1.19.

**Fix:** Upgrade to v0.1.19 or later.

## Enabling Debug Logging

Add the following to your application:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("pyintellicenter").setLevel(logging.DEBUG)
```

This will print all sent and received messages to stderr, which is useful for
diagnosing protocol-level issues.

## Getting Help

If you are still stuck, open an issue at
<https://github.com/joyfulhouse/pyintellicenter/issues> with logs and reproduction
steps.
