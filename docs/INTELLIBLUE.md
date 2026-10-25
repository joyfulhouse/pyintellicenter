# IntelliBlue evidence and consumer contract

IntelliBlue typed discovery is **not yet supported**. This is the evidence gate
for [#103](https://github.com/joyfulhouse/pyintellicenter/issues/103), not a claim
that the product is unavailable or abandoned. Existing IntelliChem/IntelliChlor
and hybrid heater support do not identify an IntelliBlue purifier.

## Evidence reviewed (2026-10-25)

Reviewed main's model, chemistry helpers, fixtures and history, #103 including
comments, and the analysis and comments in
[PR #108](https://github.com/joyfulhouse/pyintellicenter/pull/108) and
[integration PR #189](https://github.com/joyfulhouse/intellicenter/pull/189).
Those analysis branches contain app-code observations, not panel captures.
No configured MCP resources or IntelliBlue device captures were available in this sandbox.
Repository memory recall was unavailable. No live device action was performed.

The static source is Pentair Pool 4.2.21 / 21615, package
`com.pentair.pentairhome`, Hermes HBC v96 SHA-256
`ed262bd769b4ce8ba25e3faf5594f1a7d611b4db61d6b7cddd364e61be7f4526`.
Its APKPure mirror signing identity was not independently compared with Play.

| Observation | Anchor | Limit |
| --- | --- | --- |
| UI rollout gate `hyp1.itelliblueEnabled` | 80684, `0x0136f413` | Not a panel capability bit |
| Chemistry create/edit uses `BODY/PUMP/TIME`; cleaning default 02:00 | 80005, `0x01352d3f`; 83937, `0x013faa37`; 83939, `0x013fab71` | No captured subtype, reference encoding, time units/range or accepted writes |
| Purifying, bypass and protected classifications | 80023-80025; 80024, `0x013539e7` | No validated wire enum or complete state mapping |
| Protected includes regeneration, winterize, initialization, cleaning, maintenance, testing, communication failures; bypass includes ChemSoak/inactive | 80024-80025 | Labels alone prove neither commands nor physical operation |
| Pump/circuit/group helpers inspect associated `OPSTATE` | 80019, 80021, 80032 | Must establish which object reports each value and relationship direction |
| Firmware and VSF/FLOW checks can lead to Bluetooth setup | 80457, `0x01364f36`; 80458 | Caller-supplied thresholds have not established a minimum firmware or complete hardware matrix |

Registration and Bluetooth paths exist. Cloud account/registration requirements,
offline operation, Bluetooth commissioning and local read availability must be
established separately. Neither local-only provisioning nor a universal cloud
dependency is established. No firmware installation or provisioning is warranted
to resolve these questions without separate applicable authorization.

## Required sanitized evidence

Provide existing captures where possible; new physical operations require their
own authorization. Preserve object IDs consistently across related messages;
remove credentials, addresses, serials and personal names. Include:

1. Panel firmware, purifier model/firmware, pump models/firmware, body topology,
   app version and whether commissioning required cloud registration/Bluetooth.
2. Full discovery snapshot and matching read/subscription responses identifying
   exact `OBJTYP/SUBTYP`, names, `BODY/PUMP/TIME`, association rows, and raw
   `OPSTATE`, with timestamps and the reporting object IDs. Record omitted and
   unsupported fields as such, rather than substituting empty or OFF.
3. Notifications during already authorized observed states: purifying, bypass,
   protected, communication failure and recovery. Correlate app display and
   observed equipment behavior; retain unknown raw values. Do not induce
   winterization, regeneration or communication failure merely to get a fixture.
4. Multiple bodies/pumps, group membership including empty groups, dangling
   references, reassignment, object removal/recreation, reconnect snapshots and
   subscription recovery. Mark unavailable cases explicitly.
5. For settings in a later phase: authoritative units/ranges and readback plus
   independently observed behavior after an authorized edit. An acknowledgement
   or app default is insufficient validation for a writable HA entity.

Fixtures must record provenance, timestamps, firmware and sanitization. Synthetic
edge-case fixtures may test algorithms after schema validation, but must be named
synthetic and must not establish a hardware capability.

## Association API handoff for restrictions

There is **no callable purifier association API today**. The following is a
proposed consumer contract, not an exported interface or wire schema. Implement
it in the library only after evidence validates discovery and relationships;
the restrictions workstream owns interpretation and presentation of context.

A read-only observation should expose the purifier object ID, raw subtype and
raw state with reporting source ID, category (`purifying`, `bypass`, `protected`,
or `unknown`), body IDs, affiliated pump IDs, resolved group/member IDs, unresolved
references, and independent availability/freshness information. Category must
remain unknown for unrecognized/missing values; a communication fault must remain
distinguishable from ordinary protected operation and transport disconnection.

Association resolution must return both resolved IDs and unresolved dependencies.
Never infer relationships from names, ID prefixes or shared body alone. Preserve
missing, unsupported, malformed, stale and empty-but-verified inventories as
distinct outcomes. Group traversal needs cycle detection and source provenance;
deduplicate resolved IDs without discarding unresolved edges. Never replace
ordinary pump telemetry with a purifier-derived status.

Consumers need dependency IDs and structural/value change notifications for
reassignment, member changes, removal and reconnect. Exclude disconnected cached
observations from current-state claims. A connected transport or one notification
does not certify freshness of all fields. Receipt timestamps alone cannot prove
hardware freshness or snapshot completeness; purifier freshness stays unverified
until such a contract is validated and implemented. Do not invent an arbitrary timeout.

Restriction consumers may report observed context with provenance and unknown
dependencies; neither a category nor a relationship proves panel enforcement.
No control, cleaning-time edit, purifier entity or hardware capability is enabled
by this document. #103 remains open until the evidence and implementation pass
its acceptance criteria.
