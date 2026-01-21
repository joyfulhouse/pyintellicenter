#!/usr/bin/env python3
"""Investigate what the UPDATE flag means across different object types."""

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

        # Check UPDATE attribute across all object types
        object_types = [
            "BODY", "CIRCUIT", "PUMP", "HEATER", "CHEM", "SENSE",
            "SCHED", "VALVE", "CIRCGRP", "SYSTEM", "SYSTIM", "MODULE"
        ]

        print("=" * 70)
        print("UPDATE attribute investigation")
        print("=" * 70)

        for objtype in object_types:
            response = await controller.send_cmd(
                "GetParamList",
                {
                    "condition": f"OBJTYP={objtype}",
                    "objectList": [{"objnam": "INCR", "keys": ["SNAME", "UPDATE", "VER", "STATUS"]}],
                },
            )

            for obj in response.get("objectList", []):
                params = obj.get("params", {})
                update_val = params.get("UPDATE")
                if update_val and update_val != "UPDATE":
                    objnam = obj.get("objnam")
                    sname = params.get("SNAME", objnam)
                    ver = params.get("VER", "")
                    status = params.get("STATUS", "")
                    print(f"{objtype}.{objnam} ({sname}): UPDATE={update_val}, VER={ver}, STATUS={status}")

        # Also check SYSTEM object more thoroughly
        print("\n" + "=" * 70)
        print("SYSTEM object - all attributes related to updates/versions")
        print("=" * 70)

        response = await controller.send_cmd(
            "GetParamList",
            {
                "objectList": [{
                    "objnam": controller.system_info.objnam,
                    "keys": [
                        "UPDATE", "VER", "AVAIL", "ACT", "ACT1", "ACT2", "ACT3", "ACT4",
                        "STATUS", "MODE", "ENABLE", "SERVICE", "PROPNAME"
                    ]
                }],
            },
        )

        for obj in response.get("objectList", []):
            params = obj.get("params", {})
            print(f"\nSystem object ({obj.get('objnam')}):")
            for key in sorted(params.keys()):
                val = params[key]
                if val and val != key:
                    print(f"  {key}: {val}")

    finally:
        await controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
