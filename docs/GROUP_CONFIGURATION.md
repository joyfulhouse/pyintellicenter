# Group Configuration Planning

Group commissioning is **unavailable**. The library offers immutable create/edit
plans, local validation, offline edit-request previews, and readback comparison.
No firmware has verified write semantics in the evidence available for this
implementation. `controller.group_configuration_capability.can_apply` is always
`False`, and `await controller.apply_group_edit(plan)` raises
`ICGroupConfigurationError` before any network I/O. There is no bypass flag.

This is the supported first stage of [#104](https://github.com/joyfulhouse/pyintellicenter/issues/104).
Equipment association, deletion, and other equipment schemas remain separate work.

## API

```python
from pyintellicenter import GroupMemberSpec, GroupSpec, compare_group_readback

spec = GroupSpec(
    subtype="LITSHO",
    sname="Evening lights",  # Panel SNAME, not a Home Assistant display name
    members=(GroupMemberSpec("LIGHT_A"), GroupMemberSpec("LIGHT_B")),
    time_minutes=90,
)
plan = controller.validate_group_edit("GROUP_PARENT", spec)
for diagnostic in plan.diagnostics:
    print(diagnostic.code, diagnostic.path, diagnostic.message)
if plan.valid:
    preview = plan.preview_request()  # Offline static-client encoding evidence

create_plan = controller.validate_group_edit(None, spec)  # Planning only
print(controller.group_configuration_capability.remaining_gates)
```

`validate_group_edit(model, group_id, spec)` is also available as a standalone
function. Construct plans with a validator. Replacing a plan's fields requires
validation again. Members are copied to a tuple; modifying an input list or a
returned preview cannot change the plan. Unknown spec/member constructor fields
raise `TypeError`; there is no arbitrary parameter dictionary.

For feature groups use `subtype="CIRCGRP"` and give each member an explicit
`action="ON"` or `action="OFF"`, corresponding to member `ACT`. Light members
do not accept `ACT`. The conservative schema accepts finite egg timers of
1 through 1439 minutes. The inspected app uses minutes and a separate Don't Stop
branch with `TIME="1440"`; that branch is outside this initial schema. These are
planning limits, not universal firmware limits. Name length, available capacity,
supported member combinations, and body rules still need device evidence.

Validation resolves concrete object IDs and rejects missing/wrong parents,
membership-row targets, unresolved circuits, duplicates, nested groups,
unrecognized light types, malformed/duplicate existing `LISTORD`, unavailable
existing feature `ACT`, and incomplete parent timer/name data. Existing edits
require explicit `DNTSTP="OFF"`. Explicit `BODY` references must resolve;
cross-body plans and existing cross-body topology are conservatively rejected.
Absent/null body assignments do not establish firmware body compatibility.

Member tuple order is preserved in the preview. Existing rows are validated
without silently dropping unresolved references. An entirely missing row cannot
be detected from a partial model alone, so `plan.valid` means only that the
available local topology passed validation. It does not certify completeness,
freshness, capacity, or panel acceptance. Revalidate after model/reconnect changes.

## Parent Identity and Rename Semantics

The controllable parent is `OBJTYP=CIRCUIT`, `SUBTYP=LITSHO` or `CIRCGRP`.
`OBJTYP=CIRCGRP` objects are membership rows referencing `PARENT` and `CIRCUIT`.
Use `get_circuit_groups()` for parents; never create an entity per membership row.
An edit targets the existing parent ID. Trimming/changing panel `SNAME` would
rename that panel object; it does not change its ID. Home Assistant display-name
customization is separate and does not call this API.

Planning/previews/readback comparison do not change the model or subscriptions.
The existing controller reconnect lifecycle already fetches its authoritative
snapshot, reconciles removals, retains surviving object identity, and rebuilds
monitoring subscriptions. Its normal notification path handles additions.
Regression tests exercise these paths with parent renames, row replacement,
and group removal. This change introduces no second reconciliation mechanism
or new live configuration refresh operation.

## Static Encoding Evidence

The sanitized fixtures in `tests/fixtures/group_configuration/` contain
synthetic topology based on existing hardware-shaped group tests and independently
transcribed **static client request expectations**. They are not captured panel
responses or successful commissioning round trips.

Artifact: Pentair Pool 4.2.21/build 21615, `com.pentair.pentairhome`, HBC v96.
Hermes SHA-256:
`ed262bd769b4ce8ba25e3faf5594f1a7d611b4db61d6b7cddd364e61be7f4526`.
The APKPure mirror signing identity was not independently checked against Google
Play. Evidence references: [protocol PR #108](https://github.com/joyfulhouse/pyintellicenter/pull/108)
and [capability audit PR #189](https://github.com/joyfulhouse/intellicenter/pull/189).

| Builder | Evidence | Preview encoding |
|---|---|---|
| Templates | 79341, offset `0x0132ed4b`, instructions `0x704`-`0x7aa` | `SetCommand`, `CreateGroup`/`EditGroup`, `arguments` |
| Feature edit | 81309, offset `0x0138961d`, `0x16e`-`0x22a`; 81311, offset `0x0138987c` | `arguments.OBJNAM`, `OBJTYP=CIRCGRP`, `SNAME`, minute-string `TIME`; ordered `OBJLIST` members contain lowercase `objnam`, top-level `TIME`/`DNTSTP`, nested `params.ACT` |
| Light edit | 81634, offset `0x01394ff3`, `0x162`-`0x235`; 81636, offset `0x01395247` | Lowercase `arguments.objnam`, `SNAME`, minute-string `TIME`, `DNTSTP=OFF`; ordered `OBJLIST` with lowercase `objnam` and empty `params` |
| Don't Stop constants | 81330, offset `0x0138a4e1`; 81639, offset `0x013953b4` | `1440`, outside the initial schema |

The light target-ID casing is preserved from the register flow; it is not
normalized to the feature-group spelling. Previews omit `messageID` because no
request is sent. An eventual supported writer must use existing request
correlation and coordinate with the controller mutation lifecycle (including
Color Sync). The action gates owned by #100 are unchanged.

In functions 81309/81634 the non-edit branch starts with a CreateGroup template
and sets the name, leaving the template's empty membership list. That does not
establish a one-request create-with-members workflow. Create plans therefore
have no request preview. Later association steps, `CreateObjectAffect`, and
`DeleteObject` remain staged. `OBJLIST`/`TIME` do not establish per-light position
control, replace-versus-patch membership semantics, or atomicity.

## Offline Evidence Harness

```sh
.venv/bin/python scripts/plan_group_configuration.py \
  tests/fixtures/group_configuration/light_edit.json
```

The harness opens local JSON only and has no host, live-write, or replay option.
It reports validation diagnostics, the capability gate, and an edit preview
when available. Exit status 0 means locally valid (commissioning stays disabled),
2 means invalid input/plan, and 1 means a supplied readback differs or is incomplete.
Unknown fields fail rather than becoming arbitrary device parameters.

To compare previously collected, sanitized evidence, add `readback_objects` as
a separate full object list. A create comparison additionally requires
`created_group_id` obtained independently from actual device evidence. Never
identify a created object by SNAME alone. The library counterpart is:

```python
differences = compare_group_readback(plan, independently_read_model)
# For a create plan:
differences = compare_group_readback(
    create_plan, independently_read_model, created_group_id="CONFIRMED_PARENT_ID"
)
```

The comparison checks parent identity/type, `SNAME`, finite `TIME`/`DNTSTP`,
resolved membership in numeric `LISTORD` order, and feature `ACT`. It does not
compare unverified member-timer side effects or other equipment associations.
An empty diagnostic tuple means those fields match the supplied model only;
the caller must establish that model's completeness, freshness, and provenance.
A `200` acknowledgement or optimistic local update cannot establish completion.

## Remaining Device Gates

Before enabling a firmware/topology-specific writer, obtain sanitized correlated
requests/responses and independent before/after reads covering:

- Create identity and the empty-create/subsequent-membership workflow.
- Feature/light edit target casing, allowed types, name/timer/body limits,
  ordering, and replace-versus-patch behavior, including unknown fields.
- Rejection, partial application, timeout, and disconnect between acknowledgement
  and readback; verify which fields changed without assuming atomicity.
- Removal/reconnect subscription reconciliation and downstream entity identity.
- Explicit deletion/association schemas and actionable dependency failures before
  adding those operations.

An uncertain create or delete must not be retried blindly. Recovery must report
uncertainty and reconcile authoritative evidence; no automatic destructive
rollback or fabricated rollback success is supported. No live commissioning,
light action replay, or other device writes were performed for this change.
Downstream HA configuration actions remain gated on a future verified writer;
no secondary integration PR or library dependency bump is needed now. Track
remaining implementation in [intellicenter #188](https://github.com/joyfulhouse/intellicenter/issues/188).
