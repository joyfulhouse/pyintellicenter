"""Inspect sanitized group configuration evidence offline; never open a socket."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pyintellicenter import (
    GroupMemberSpec,
    GroupSpec,
    ICGroupConfigurationError,
    ICModelController,
    PoolModel,
    compare_group_readback,
)


def report_evidence(data: dict[str, Any]) -> dict[str, Any]:
    """Plan against explicit objects; optionally compare a separate readback."""
    allowed = {
        "evidence",
        "group_id",
        "objects",
        "spec",
        "expected_request",
        "readback_objects",
        "created_group_id",
    }
    if unknown := data.keys() - allowed:
        raise ValueError(f"Unknown evidence fields: {sorted(unknown)}")
    spec_data = dict(data["spec"])
    spec_data["members"] = tuple(GroupMemberSpec(**member) for member in spec_data["members"])
    spec = GroupSpec(**spec_data)
    model = PoolModel()
    model.add_objects(data["objects"])
    controller = ICModelController("offline.invalid", model)
    plan = controller.validate_group_edit(data["group_id"], spec)
    report: dict[str, Any] = {
        "valid": plan.valid,
        "diagnostics": [asdict(problem) for problem in plan.diagnostics],
        "capability": asdict(controller.group_configuration_capability),
    }
    try:
        report["static_request_preview"] = plan.preview_request()
    except ICGroupConfigurationError as error:
        report["preview_unavailable"] = str(error)
    if "readback_objects" in data:
        readback = PoolModel()
        readback.add_objects(data["readback_objects"])
        report["readback_diagnostics"] = [
            asdict(problem)
            for problem in compare_group_readback(
                plan, readback, created_group_id=data.get("created_group_id")
            )
        ]
    return report


def main() -> int:
    """Print a local evidence report; validity does not imply commissioning support."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="Sanitized offline evidence JSON")
    args = parser.parse_args()
    try:
        report = report_evidence(json.loads(args.fixture.read_text()))
    except (KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))
    if not report["valid"]:
        return 2
    return 1 if report.get("readback_diagnostics") else 0


if __name__ == "__main__":
    raise SystemExit(main())
