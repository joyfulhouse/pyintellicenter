# Field receipt provenance

`ICModelController.field_receipt(objnam, attribute)` returns `None` if no field
receipt is known for this connection attempt, or a new dictionary containing:

| Key | Meaning |
| --- | --- |
| `age_seconds` | Monotonic seconds since the controller ingested this field |
| `connection_generation` | Local counter incremented at each `start()` attempt; not a panel sequence number |
| `current_connection` | Receipt belongs to an established generation whose transport is currently connected |

```python
receipt = controller.field_receipt("C1", "FREEZE")
if receipt is None:
    print("No receipt in this connection attempt; cached value may survive")
else:
    print(receipt["age_seconds"], receipt["current_connection"])
```

This is a local receipt API, **not a guarantee of panel freshness**. It records
fields in the initial object snapshot and model update ingress (subscription
responses, monitoring backfill and notifications). Raw query responses not applied
to the model do not create receipts. Direct model edits, requested writes and
command acknowledgements do not create receipts. Null, malformed field values and
unsupported field echoes can have receipts; interpret value validity separately.
Receipts contain no parameter values or wall-clock timestamps.

Receiving an unchanged value refreshes its receipt without changing the existing
value-change callback/subscription contract. Download or query receipts when
needed; there is no receipt-only event or polling task. Queries do not scan the
model. Metadata is bounded by fields ingested for modeled objects within the
connection attempt. Removed/replaced object identities cannot inherit receipts.

Every connection attempt clears receipts even when cached model properties
survive. A snapshot or subscription response omitting a field does not establish
that field's receipt. A failed initialization leaves any partial receipts marked
non-current after transport teardown. Disconnection preserves receipt ages for
diagnostics but reports `current_connection=false`. After reconnection, old
receipts are absent. A generation counts attempts, including failed attempts.

The API establishes neither device sample time, inventory completeness, validated
cover assignment schema, nor physical action. An old receipt may describe an
unchanged value, and a recent receipt may repeat stale panel data. No arbitrary
expiry threshold, hardware capability, all-clear assessment or command blocking
is derived from age. Callers must retain independent unknown dependencies.

This software contract supports integration restriction diagnostics for
[intellicenter #187](https://github.com/joyfulhouse/intellicenter/issues/187).
Cover assignment validation still requires named-firmware snapshot/subscription
captures of assignment type, parent/target references, empty inventory and
update/removal behavior. Purifier discovery and applicability belong to
[#103](https://github.com/joyfulhouse/pyintellicenter/issues/103) and its association
handoff in [PR #119](https://github.com/joyfulhouse/pyintellicenter/pull/119).
No purifier implementation or guessed cover assignment object is introduced here.
