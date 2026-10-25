# Stored panel history: evidence and retrieval requirements

Tracking: [#101](https://github.com/joyfulhouse/pyintellicenter/issues/101).
Assessment date: 2026-10-25. Local availability is **unknown**, not unsupported.
There is no public typed history API or history capability advertisement.

## What the evidence establishes

Pentair Pool 4.2.21 / 21615 contains a `ReadHistoryMessage` template with
string `timeStart`, `timeEnd`, and `messageID` fields (Hermes function 83343,
offset `0x013e4025`). Functions 83255 and 83287 replace the dates; 83261
sends through the shared manager; 83258 consumes returned `objectList` data.
The seven-day/end-of-day UI helpers do not establish retention or wire bounds.

This is static app evidence, not a local panel capture. The inspected Hermes
asset SHA-256 is
`ed262bd769b4ce8ba25e3faf5594f1a7d611b4db61d6b7cddd364e61be7f4526`.
See the issue and [analysis PR #108](https://github.com/joyfulhouse/pyintellicenter/pull/108)
for provenance and the pending full protocol reference. Searches of current
source, tracked fixtures, Git history, and the analysis PR found no correlated
local history request/response or validated sample schema. No configured MCP
resource supplied panel evidence in this sandbox. No device request was sent.

The shared sender supports multiple connection paths. Its use does not prove
that history is stored on the panel, that cloud access is required, or that
local retrieval is unavailable. An acknowledgement or an empty `objectList`
alone would not establish a complete successful retrieval.

## Evidence needed to unblock implementation

Provide sanitized, correlated requests and all response frames from a known
firmware/model and local TCP/6681 or WebSocket/6680 connection. Establish that
the transaction did not use the cloud; include transport, connection lifetime,
request IDs, and capture ordering. Preserve field structure, values needed for
time/unit interpretation, and stable pseudonyms for series IDs. Remove tokens,
passwords, addresses, and personal information. A local failure is evidence for
that firmware/transport only, not a universal lack of support.

| Question | Required observations |
|---|---|
| Time | Exact request and sample formats; epoch and seconds/milliseconds if numeric; panel timezone and UTC offset; inclusive/exclusive endpoints; DST ambiguous/nonexistent times. Do not infer timezone from the host or current panel clock. |
| Series | Stable identity, equipment/attribute association, sample shape, quality/missing values, instantaneous values versus interval aggregates or cumulative counters. |
| Units | Explicit units or independent correlation to known measurements; English/metric behavior and whether historical units change when panel configuration changes. |
| Retention | Known nonempty and empty periods, oldest accessible samples, granularity, truncation, and any firmware-dependent limits. A seven-day UI default is insufficient. |
| Completion | Full multi-frame sequence; request-ID correlation; terminal markers, cursors/page tokens, ordering and limits; distinguish empty completion from a dropped/partial response. |
| Failure | Unsupported/error replies, cancellation, late/duplicate frames, disconnect mid-transfer, and reconnect behavior with fresh request IDs. |

Start with a narrow known nonempty range and an empty range using dates whose
wire encoding has been independently verified. Widen only within established
limits to investigate retention and paging. Do not invent request dates from
the template's string type. Captures may be supplied from an existing authorized
session; implementation permission does not authorize panel mutations.

## Contract to implement after validation

- Keep history outside `PoolModel` and the live `NotifyList` pipeline. Historical
  samples must never overwrite live temperatures, equipment status, or subscriptions.
- Accept timezone-aware start/end values, reject reversed/ambiguous ranges, and
  convert only according to the validated wire contract. Preserve source time,
  normalized UTC time, series identity, unit, and quality without guessing.
- Bound total time range, per-request window, pages, frames/bytes, sample count,
  and elapsed time. Yield bounded typed batches with backpressure. The existing
  transport buffer cap alone does not bound an entire history operation.
- Deduplicate by validated series/sample identity. Define conflict handling for
  equal timestamps with different values; do not silently replace unknown data
  or assume arrival order is chronological.
- Expose partial completion explicitly. Never equate timeout, an acknowledgement,
  or a short page with completion unless the wire contract proves that rule.
- Propagate cancellation and release pending work. Isolate late replies and
  reconnect generations. Resume/retry only with verified paging and idempotence;
  do not add unbounded automatic replay alongside live requests.
- Test empty ranges, malformed samples, unknown series/units, timestamp and DST
  errors, out-of-order/conflicting duplicates, truncation, resource limits,
  cancellation, late frames, and reconnect using provenance-labelled captures.
  Synthetic edge cases must be labelled synthetic, not presented as panel evidence.

These are implementation acceptance requirements, not an invented wire schema.
No retrieval scaffold or fabricated fixtures are needed until the contract is
known. Keep #101 open while local availability and semantics remain unresolved.

HA ingestion is a separate dependency: see the integration's
[stored-history assessment](https://github.com/joyfulhouse/intellicenter/blob/main/docs/stored-history.md).
