#!/usr/bin/env python3
"""Audit: Compare tracked attributes vs what device actually returns."""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from pyintellicenter import ICModelController, PoolModel  # noqa: E402
from pyintellicenter.attributes import ALL_ATTRIBUTES_BY_TYPE  # noqa: E402


async def main():
    host = os.getenv("INTELLICENTER_HOST", "10.100.11.60")
    port = int(os.getenv("INTELLICENTER_PORT", "6681"))

    print(f"Connecting to IntelliCenter at {host}:{port}...")

    model = PoolModel()
    controller = ICModelController(host, model, port)

    try:
        await controller.start()
        print(f"Connected to: {controller.system_info.prop_name}")
        print(f"Software version: {controller.system_info.sw_version}")
        print()

        # Collect all objects by type
        objects_by_type: dict[str, list] = {}
        for obj in model:
            objtype = obj.objtype
            if objtype not in objects_by_type:
                objects_by_type[objtype] = []
            objects_by_type[objtype].append(obj)

        print("=" * 70)
        print("ATTRIBUTE AUDIT: Tracked vs Device")
        print("=" * 70)

        total_missing = 0
        total_extra = 0

        for objtype in sorted(objects_by_type.keys()):
            objects = objects_by_type[objtype]
            tracked_attrs = ALL_ATTRIBUTES_BY_TYPE.get(objtype, set())

            # Collect all attributes seen on device for this type
            device_attrs: set[str] = set()
            for obj in objects:
                device_attrs.update(obj.attribute_keys)

            # Find differences
            missing_in_lib = device_attrs - tracked_attrs - {"OBJTYP", "HNAME", "OBJNAM"}
            extra_in_lib = tracked_attrs - device_attrs

            # Filter out attrs that returned key=value (not actually set)
            actually_missing: set[str] = set()
            for attr in missing_in_lib:
                for obj in objects:
                    val = obj[attr]
                    if val is not None and val != attr:  # Has a real value
                        actually_missing.add(attr)
                        break

            if actually_missing or extra_in_lib:
                print(f"\n{objtype} ({len(objects)} objects):")
                print("-" * 50)

                if actually_missing:
                    print("  NOT TRACKED (device has values):")
                    for attr in sorted(actually_missing):
                        # Show sample values
                        samples = []
                        for obj in objects[:3]:
                            val = obj[attr]
                            if val is not None and val != attr:
                                samples.append(f"{val}")
                        sample_str = ", ".join(samples[:3])
                        print(f"    {attr}: {sample_str}")
                    total_missing += len(actually_missing)

                if extra_in_lib:
                    print("  TRACKED BUT NOT SEEN:")
                    for attr in sorted(extra_in_lib):
                        print(f"    {attr}")
                    total_extra += len(extra_in_lib)
            else:
                print(f"\n{objtype} ({len(objects)} objects): ✓ All attributes tracked")

        print("\n" + "=" * 70)
        print(f"SUMMARY: {total_missing} untracked attributes with values, "
              f"{total_extra} tracked but not seen")
        print("=" * 70)

        # Also show raw count of what we're tracking
        print("\nTracked attribute counts by type:")
        for objtype in sorted(ALL_ATTRIBUTES_BY_TYPE.keys()):
            count = len(ALL_ATTRIBUTES_BY_TYPE[objtype])
            obj_count = len(objects_by_type.get(objtype, []))
            print(f"  {objtype}: {count} attrs, {obj_count} objects on device")

    finally:
        await controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
