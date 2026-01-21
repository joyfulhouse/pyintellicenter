#!/usr/bin/env python3
"""Search for smart valve controls - might be under BODY, CIRCUIT, or other types."""

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

        # Check BODY objects for valve-related attributes
        print("=" * 80)
        print("BODY OBJECTS (pool/spa modes)")
        print("=" * 80)
        response = await controller.send_cmd(
            "GetParamList",
            {
                "condition": "OBJTYP=BODY",
                "objectList": [{"objnam": "INCR", "keys": [
                    "OBJTYP", "SUBTYP", "SNAME", "STATUS", "MODE", "VALVE",
                    "INTAKE", "RETURN", "SPILLWAY", "DRAIN", "SHARE",
                    "HEATER", "HTSRC", "HTMODE", "TEMP", "LOTMP", "HITMP",
                ]}],
            },
        )
        for obj in response.get("objectList", []):
            print(f"\n{obj.get('objnam')}: {obj.get('params', {}).get('SNAME', 'N/A')}")
            for k, v in sorted(obj.get("params", {}).items()):
                if v != k and v is not None:
                    print(f"  {k:12} = {v!r}")

        # Check for any INTELLI* subtypes in valves or other objects
        print("\n" + "=" * 80)
        print("SEARCHING FOR 'INTELLI' OR 'SMART' IN ALL OBJECTS")
        print("=" * 80)

        for objtype in ["VALVE", "CIRCUIT", "MODULE", "PANEL"]:
            response = await controller.send_cmd(
                "GetParamList",
                {
                    "condition": f"OBJTYP={objtype}",
                    "objectList": [{"objnam": "INCR", "keys": [
                        "OBJTYP", "SUBTYP", "SNAME", "STATUS", "MODE",
                        "VALVE", "ASSIGN", "CIRCUIT", "PARENT",
                    ]}],
                },
            )
            for obj in response.get("objectList", []):
                params = obj.get("params", {})
                subtyp = params.get("SUBTYP", "")
                sname = params.get("SNAME", "")
                # Look for anything that might be smart/intelli
                if subtyp and subtyp != "SUBTYP":
                    print(f"\n{objtype} {obj.get('objnam')}: SUBTYP={subtyp}, SNAME={sname}")
                    for k, v in sorted(params.items()):
                        if v != k and v is not None:
                            print(f"  {k:12} = {v!r}")

        # Look at the hardware definition for valve configurations
        print("\n" + "=" * 80)
        print("HARDWARE DEFINITION (looking for valve config)")
        print("=" * 80)
        response = await controller.send_cmd("GetHardwareDefinition", {})

        # Search for anything valve-related in the response
        def search_for_valves(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if "valve" in k.lower() or "intake" in k.lower() or "return" in k.lower() or "spill" in k.lower():
                        print(f"{path}.{k} = {v!r}")
                    search_for_valves(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    search_for_valves(item, f"{path}[{i}]")

        search_for_valves(response)

        # Check CIRCGRP for spillway controls
        print("\n" + "=" * 80)
        print("CIRCUIT GROUPS (might include spillway)")
        print("=" * 80)
        response = await controller.send_cmd(
            "GetParamList",
            {
                "condition": "OBJTYP=CIRCGRP",
                "objectList": [{"objnam": "INCR", "keys": [
                    "OBJTYP", "SUBTYP", "SNAME", "STATUS", "CIRCUIT", "USE",
                ]}],
            },
        )
        for obj in response.get("objectList", []):
            print(f"\n{obj.get('objnam')}: {obj.get('params', {}).get('SNAME', 'N/A')}")
            for k, v in sorted(obj.get("params", {}).items()):
                if v != k and v is not None:
                    print(f"  {k:12} = {v!r}")

    finally:
        await controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
