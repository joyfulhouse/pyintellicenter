# Troubleshooting

Common problems with pyintellicenter and how to resolve them.

## Common Issues

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
