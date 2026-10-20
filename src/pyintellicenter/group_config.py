"""Read-only group configuration planning based on static app evidence.

Request previews are research artifacts, not supported commissioning commands.
No panel/firmware combination has verified group write semantics yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .attributes import LIGHT_SUBTYPES, NULL_OBJNAM
from .exceptions import ICError

if TYPE_CHECKING:
    from .model import PoolModel, PoolObject


@dataclass(frozen=True, slots=True)
class GroupMemberSpec:
    """One ordered circuit reference; ACT is required only for feature groups."""

    circuit: str
    action: Literal["ON", "OFF"] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.circuit, str):
            raise TypeError("circuit must be a string")
        if self.action is not None and not isinstance(self.action, str):
            raise TypeError("action must be a string or None")


@dataclass(frozen=True, slots=True)
class GroupSpec:
    """Desired panel SNAME, ordered members, and finite egg timer in minutes.

    This conservative planning schema excludes Don't Stop, per-light position,
    body reassignment, and arbitrary parameters. It is not a patch document.
    """

    subtype: Literal["CIRCGRP", "LITSHO"]
    sname: str
    members: tuple[GroupMemberSpec, ...]
    time_minutes: int = 720

    def __post_init__(self) -> None:
        if not isinstance(self.subtype, str) or not isinstance(self.sname, str):
            raise TypeError("subtype and sname must be strings")
        if type(self.time_minutes) is not int:
            raise TypeError("time_minutes must be an integer")
        members = tuple(self.members)
        if any(not isinstance(member, GroupMemberSpec) for member in members):
            raise TypeError("members must contain GroupMemberSpec values")
        object.__setattr__(self, "members", members)


@dataclass(frozen=True, slots=True)
class GroupDiagnostic:
    """A structural problem in the desired spec or the available topology."""

    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class GroupConfigurationCapability:
    """Evidence gates, independent of whether a proposed spec is valid."""

    can_apply: bool = False
    evidence: str = "static_client_only"
    remaining_gates: tuple[str, ...] = (
        "firmware-specific create/edit request and response captures",
        "membership replace-versus-patch and ordering semantics",
        "body constraints, supported member types, name and timer limits",
        "authoritative readback including partial application and timeout outcomes",
        "created object identity and deletion/dependency semantics",
    )


class ICGroupConfigurationError(ICError):
    """A group plan cannot be previewed or commissioning is unavailable."""


@dataclass(frozen=True, slots=True)
class GroupEditPlan:
    """Immutable result of validate_group_edit; valid does not authorize writes.

    Construct plans through the validator. Manually constructed or replaced
    plans must be validated before producing a request preview.
    """

    group_id: str | None
    spec: GroupSpec
    diagnostics: tuple[GroupDiagnostic, ...] = ()
    _validated: bool = field(default=False, init=False, repr=False, compare=False)

    @property
    def valid(self) -> bool:
        """Whether the available topology passes conservative local validation."""
        return self._validated and not self.diagnostics

    def preview_request(self) -> dict[str, Any]:
        """Return a fresh EditGroup research payload, without a messageID.

        See docs/GROUP_CONFIGURATION.md for static evidence anchors. Creation
        is planned but has no preview: the app initially creates an empty group
        and its later membership workflow needs separate validation.
        """
        if not self.valid:
            raise ICGroupConfigurationError("Invalid group plan; inspect diagnostics")
        if self.group_id is None:
            raise ICGroupConfigurationError("Create membership workflow is not verified")
        time = str(self.spec.time_minutes)
        arguments: dict[str, Any] = {"SNAME": self.spec.sname.strip(), "TIME": time}
        members: list[dict[str, Any]] = []
        if self.spec.subtype == "CIRCGRP":
            arguments.update(OBJNAM=self.group_id, OBJTYP="CIRCGRP")
            members = [
                {
                    "objnam": member.circuit,
                    "TIME": time,
                    "DNTSTP": "OFF",
                    "params": {"ACT": member.action},
                }
                for member in self.spec.members
            ]
        else:
            arguments.update(objnam=self.group_id, DNTSTP="OFF")
            members = [{"objnam": member.circuit, "params": {}} for member in self.spec.members]
        arguments["OBJLIST"] = members
        return {"command": "SetCommand", "method": "EditGroup", "arguments": arguments}


def _reference(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value != NULL_OBJNAM
        and not any(ord(char) < 32 or char.isspace() or char in ",:&=" for char in value)
    )


def _order(value: object) -> int | None:
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    if type(value) is int and value >= 0:
        return value
    return None


def validate_group_edit(model: PoolModel, group_id: str | None, spec: GroupSpec) -> GroupEditPlan:
    """Plan creation (None) or editing using only the supplied model.

    Reject incomplete affected topology rather than silently dropping unresolved
    rows as the read-only display helpers may do. A model cannot establish its
    own snapshot completeness or freshness; this is one reason writes stay gated.
    """
    if not isinstance(spec, GroupSpec):
        raise TypeError("spec must be a GroupSpec")
    problems: list[GroupDiagnostic] = []

    def problem(code: str, path: str, message: str) -> None:
        problems.append(GroupDiagnostic(code, path, message))

    if spec.subtype not in ("CIRCGRP", "LITSHO"):
        problem("unsupported_subtype", "subtype", "Use a CIRCGRP or LITSHO circuit parent")
    if not spec.sname.strip() or any(ord(char) < 32 for char in spec.sname):
        problem("invalid_name", "sname", "Panel SNAME must be nonblank with no control characters")
    if not 1 <= spec.time_minutes < 1440:
        problem(
            "unsupported_timer", "time_minutes", "Plan finite timers from 1 through 1439 minutes"
        )
    if not spec.members:
        problem(
            "empty_members", "members", "Plan at least one member; deletion is a separate operation"
        )

    parent = None
    if group_id is not None:
        if not _reference(group_id):
            problem("invalid_reference", "group_id", "Use one concrete parent object identifier")
        else:
            parent = model[group_id]
            if parent is None:
                problem(
                    "missing_parent", "group_id", "Group parent is absent; refresh the topology"
                )
            elif parent.objtype != "CIRCUIT" or parent.subtype != spec.subtype:
                problem(
                    "invalid_parent",
                    "group_id",
                    "Target must be a matching CIRCUIT parent, not a row",
                )
            else:
                _validate_existing(model, parent, problems)

    seen: set[str] = set()
    bodies: set[str] = set()
    if parent is not None:
        _validate_body(model, parent, "group_id.BODY", bodies, problems)
    for index, member in enumerate(spec.members):
        path = f"members[{index}]"
        if not _reference(member.circuit):
            problem("invalid_reference", path, "Use one concrete circuit object identifier")
            continue
        if member.circuit in seen:
            problem("duplicate_member", path, "Each circuit may appear only once")
        seen.add(member.circuit)
        circuit = model[member.circuit]
        if circuit is None:
            problem("missing_circuit", path, "Circuit is absent; refresh the topology")
        elif circuit.objtype != "CIRCUIT" or circuit.subtype in (None, "CIRCGRP", "LITSHO"):
            problem(
                "unsupported_member",
                path,
                "Nested groups, rows and incomplete circuits are unsupported",
            )
        elif spec.subtype == "LITSHO" and circuit.subtype not in LIGHT_SUBTYPES:
            problem("unsupported_member", path, "Light groups require a recognized light subtype")
        if circuit is not None:
            _validate_body(model, circuit, f"{path}.BODY", bodies, problems)
        if spec.subtype == "CIRCGRP" and member.action not in ("ON", "OFF"):
            problem("invalid_action", f"{path}.action", "Feature members require ON or OFF ACT")
        if spec.subtype == "LITSHO" and member.action is not None:
            problem(
                "unsupported_action", f"{path}.action", "Light-member ACT is outside this schema"
            )
    if len(bodies) > 1:
        problem("body_conflict", "members", "Cross-body configuration needs device evidence")
    plan = GroupEditPlan(group_id, spec, tuple(problems))
    object.__setattr__(plan, "_validated", True)
    return plan


def _validate_body(
    model: PoolModel,
    obj: PoolObject,
    path: str,
    bodies: set[str],
    problems: list[GroupDiagnostic],
) -> None:
    body = obj["BODY"]
    if body is None or body == NULL_OBJNAM:
        return
    resolved = model[body] if _reference(body) else None
    if resolved is None or resolved.objtype != "BODY":
        problems.append(GroupDiagnostic("invalid_body", path, "BODY must resolve to a body object"))
    else:
        bodies.add(body)


def _validate_existing(
    model: PoolModel, parent: PoolObject, problems: list[GroupDiagnostic]
) -> None:
    rows = [row for row in model.get_by_type("CIRCGRP") if row["PARENT"] == parent.objnam]
    seen: set[str] = set()
    orders: set[int] = set()
    bodies: set[str] = set()
    _validate_body(model, parent, "group_id.BODY", bodies, problems)
    if not isinstance(parent["SNAME"], str) or _order(parent["TIME"]) is None:
        problems.append(
            GroupDiagnostic(
                "incomplete_topology",
                "group_id",
                "Read existing SNAME and TIME before planning an edit",
            )
        )
    if parent["DNTSTP"] != "OFF":
        problems.append(
            GroupDiagnostic(
                "unsupported_timer",
                "group_id.DNTSTP",
                "Only explicit finite-timer topology is currently modeled",
            )
        )
    if not rows:
        problems.append(
            GroupDiagnostic("incomplete_topology", "rows", "No membership rows available")
        )
    for row in rows:
        ref, order = row["CIRCUIT"], _order(row["LISTORD"])
        path = f"rows.{row.objnam}"
        circuit = model[ref] if _reference(ref) else None
        if (
            circuit is None
            or circuit.objtype != "CIRCUIT"
            or circuit.subtype in (None, "LITSHO", "CIRCGRP")
        ):
            problems.append(
                GroupDiagnostic(
                    "invalid_row_reference", path, "Resolve the existing CIRCUIT reference"
                )
            )
        elif parent.subtype == "LITSHO" and circuit.subtype not in LIGHT_SUBTYPES:
            problems.append(
                GroupDiagnostic(
                    "unsupported_member", path, "Existing light member has an unsupported subtype"
                )
            )
        if circuit is not None:
            _validate_body(model, circuit, f"{path}.BODY", bodies, problems)
        if isinstance(ref, str):
            if ref in seen:
                problems.append(
                    GroupDiagnostic(
                        "duplicate_member", path, "Existing membership duplicates a circuit"
                    )
                )
            seen.add(ref)
        if order is None or order in orders:
            problems.append(
                GroupDiagnostic(
                    "invalid_order", path, "Existing LISTORD must be nonnegative and unique"
                )
            )
        if order is not None:
            orders.add(order)
        if parent.subtype == "CIRCGRP" and row["ACT"] not in ("ON", "OFF"):
            problems.append(
                GroupDiagnostic(
                    "invalid_action", path, "Existing member ACT is unavailable or unsupported"
                )
            )
    if len(bodies) > 1:
        problems.append(
            GroupDiagnostic(
                "body_conflict", "rows", "Existing cross-body topology needs device evidence"
            )
        )


def compare_group_readback(
    plan: GroupEditPlan, model: PoolModel, *, created_group_id: str | None = None
) -> tuple[GroupDiagnostic, ...]:
    """Compare explicit configuration evidence with a plan, without applying it.

    Supply an authoritative, freshly read model, not an acknowledgement or
    optimistic NotifyList. An empty result means only the compared fields match;
    it never certifies write completion, atomicity, or snapshot completeness.
    Creation requires an independently established ID, never a name match.
    """
    if not plan.valid:
        return plan.diagnostics or (
            GroupDiagnostic(
                "unvalidated_plan", "plan", "Construct the plan with validate_group_edit"
            ),
        )
    if plan.group_id is not None and created_group_id is not None:
        raise ValueError("created_group_id is only valid for a create plan")
    group_id = plan.group_id if plan.group_id is not None else created_group_id
    if group_id is None:
        return (
            GroupDiagnostic(
                "unknown_created_id",
                "group_id",
                "Supply an independently established created parent ID",
            ),
        )
    checked = validate_group_edit(model, group_id, plan.spec)
    if not checked.valid:
        return checked.diagnostics
    parent = model[group_id]
    assert parent is not None
    problems: list[GroupDiagnostic] = []
    for key, expected in (
        ("SNAME", plan.spec.sname.strip()),
        ("TIME", str(plan.spec.time_minutes)),
    ):
        if parent[key] != expected:
            problems.append(
                GroupDiagnostic(
                    "readback_mismatch", key, f"Expected {expected!r}; observed {parent[key]!r}"
                )
            )
    rows = sorted(
        (row for row in model.get_by_type("CIRCGRP") if row["PARENT"] == group_id),
        key=lambda row: _order(row["LISTORD"]) or 0,
    )
    observed = tuple(
        GroupMemberSpec(row["CIRCUIT"], row["ACT"] if plan.spec.subtype == "CIRCGRP" else None)
        for row in rows
    )
    if observed != plan.spec.members:
        problems.append(
            GroupDiagnostic(
                "readback_mismatch", "members", "Ordered membership or member ACT differs"
            )
        )
    return tuple(problems)
