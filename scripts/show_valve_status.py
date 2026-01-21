#!/usr/bin/env python3
"""Query and display all valve attributes from the IntelliCenter."""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from pyintellicenter import ICBaseController  # noqa: E402


async def main():
    host = os.getenv("INTELLICENTER_HOST", "10.100.11.60")
    port = int(os.getenv("INTELLICENTER_PORT", "6681"))

    print(f"Connecting to IntelliCenter at {host}:{port}...")

    controller = ICBaseController(host, port)

    try:
        await controller.start()
        print(f"Connected to: {controller.system_info.prop_name}\n")

        # Query ALL attributes for VALVE objects
        response = await controller.send_cmd(
            "GetParamList",
            {
                "condition": "OBJTYP=VALVE",
                "objectList": [
                    {
                        "objnam": "INCR",
                        "keys": [
                            # Query everything we know about plus common unknowns
                            "OBJTYP",
                            "SUBTYP",
                            "OBJNAM",
                            "HNAME",
                            "SNAME",
                            "PARENT",
                            "BODY",
                            "STATUS",
                            "ASSIGN",
                            "CIRCUIT",
                            "DLY",
                            "READY",
                            "STATIC",
                            "MODE",
                            "ACT",
                            "ENABLE",
                            "NORMAL",
                            "SELECT",
                            "USE",
                            "LISTORD",
                            "PERMIT",
                            "SHOMNU",
                            "SOURCE",
                            "FEATR",
                            "MANUAL",
                            "AUTO",
                        ],
                    }
                ],
            },
        )

        valves = response.get("objectList", [])
        print(f"Found {len(valves)} valve(s):\n")
        print("=" * 80)

        for valve in valves:
            objnam = valve.get("objnam", "UNKNOWN")
            params = valve.get("params", {})

            print(f"\nValve: {objnam}")
            print("-" * 40)

            # Show all attributes that have real values
            for key in sorted(params.keys()):
                value = params[key]
                # Skip if value equals key (means attribute doesn't exist)
                if value != key and value is not None:
                    print(f"  {key:12} = {value!r}")

        print("\n" + "=" * 80)
        print("\nKey attributes to understand:")
        print("  STATUS: Valve actuator state (ON/OFF or position?)")
        print("  ASSIGN: Valve role (NONE, INTAKE, RETURN)")
        print("  CIRCUIT: Circuit that controls this valve")
        print("  BODY: Which body the valve is associated with")

    finally:
        await controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
