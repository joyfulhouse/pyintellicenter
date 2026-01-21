#!/usr/bin/env python3
"""Show the actual values of newly discovered attributes."""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from pyintellicenter import ICBaseController  # noqa: E402

# New attributes discovered that we're not tracking
NEW_ATTRS_BY_TYPE = {
    "BODY": ["SETTMP"],
    "CHEM": ["MODE", "PROBE", "READY", "STATIC", "TEMP"],
    "CIRCGRP": ["USE"],
    "MODULE": ["READY"],
    "PANEL": ["READY"],
    "PERMIT": ["READY"],
    "PMPCIRC": ["READY", "STATIC"],
    "PRESS": ["READY"],
    "PUMP": ["PRIM", "READY", "STATIC"],
    "REMBTN": ["READY"],
    "REMOTE": ["READY"],
    "SCHED": ["READY"],
    "SENSE": ["READY"],
    "SYSTEM": ["ACT3", "ACT4", "ENABLE", "PERMIT", "PORT", "READY", "STATIC", "UPDATE"],
    "SYSTIM": ["CALIB", "READY"],
    "VALVE": ["READY"],
}


async def main():
    host = os.getenv("INTELLICENTER_HOST", "10.100.11.60")
    port = int(os.getenv("INTELLICENTER_PORT", "6681"))

    print(f"Connecting to IntelliCenter at {host}:{port}...")

    controller = ICBaseController(host, port)

    try:
        await controller.start()
        print(f"Connected to: {controller.system_info.prop_name}\n")

        print("=" * 70)
        print("NEW ATTRIBUTES - Actual Values from Device")
        print("=" * 70)

        for objtype, attrs in sorted(NEW_ATTRS_BY_TYPE.items()):
            response = await controller.send_cmd(
                "GetParamList",
                {
                    "condition": f"OBJTYP={objtype}",
                    "objectList": [{"objnam": "INCR", "keys": ["SNAME"] + attrs}],
                },
            )

            objects = response.get("objectList", [])
            if objects:
                print(f"\n{objtype} ({len(objects)} objects):")
                print("-" * 50)

                for obj in objects[:3]:  # Show up to 3 examples
                    objnam = obj.get("objnam")
                    params = obj.get("params", {})
                    sname = params.get("SNAME", objnam)

                    values = []
                    for attr in attrs:
                        val = params.get(attr)
                        if val and val != attr:  # Has real value
                            values.append(f"{attr}={val}")

                    if values:
                        print(f"  {sname}: {', '.join(values)}")

    finally:
        await controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
