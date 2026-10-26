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
responses, monitoring backfill, telemetry reconciliation and notifications). Raw query responses not applied
to the model do not create receipts. Direct model edits, requested writes and
command acknowledgements do not create receipts. Null, malformed field values and
unsupported field echoes can have receipts; interpret value validity separately.
Receipts contain no parameter values or wall-clock timestamps.

Receiving an unchanged value refreshes its receipt without changing the existing
value-change callback/subscription contract. Download or query receipts when
needed; there is no receipt-only event or receipt polling task. Queries do not scan the
model. Metadata is bounded by fields ingested for modeled objects within the
connection attempt. Removed/replaced object identities cannot inherit receipts.

The default-on [telemetry reconciliation worker](API.md#authoritative-telemetry-reconciliation)
refreshes receipts only for accepted requested fields. A response from an obsolete
connection/generation, a replaced object, or a pair observed during the request
does not create a readback receipt. Omitted fields remain untouched. While reads
succeed, inventories of at most 50 target pairs are fully read every completed
reconciliation tick. Larger inventories with stable membership and tracked keys
are covered within `R = ceil(target_pairs / 50)` completed ticks; after the final
target-set change, within `2 * R` completed ticks using the settled pair count.
Continuous churn has no finite coverage bound.

Ticks are scheduled every `interval` (60 seconds by default); overrunning a slot
skips missed ticks without bursts. Without scheduling delays, a tick taking `d`
seconds occupies
`max(1, floor(d / interval) + 1)` interval slots before the next start:
`ceil(d / interval)` slots unless completion lands exactly on a boundary, when
one more slot is skipped. Here `d` includes the request and local processing;
scheduling delays add elapsed time. Request duration includes queueing, write
and response, bounded by the existing total deadline
(`ICConnection.__init__`: `request_total_timeout=60.0` seconds by default).

Receipt age remains local ingestion age, not device sample age. SOLAR coverage
is inferred; ICHLOR salt is defensive with cause
**UNVERIFIED**.
The [firmware alias RCA](https://github.com/joyfulhouse/intellicenter/issues/212#issuecomment-6422806614)
explains the temperature limitation; unit tests are not physical firmware validation.

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
