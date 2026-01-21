#!/usr/bin/env python3
"""Discover ALL attributes by querying with empty keys (returns everything)."""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from pyintellicenter import ICBaseController  # noqa: E402
from pyintellicenter.attributes import ALL_ATTRIBUTES_BY_TYPE  # noqa: E402


async def main():
    host = os.getenv("INTELLICENTER_HOST", "10.100.11.60")
    port = int(os.getenv("INTELLICENTER_PORT", "6681"))

    print(f"Connecting to IntelliCenter at {host}:{port}...")

    controller = ICBaseController(host, port)

    try:
        await controller.start()
        print(f"Connected to: {controller.system_info.prop_name}\n")

        # Object types to check
        object_types = [
            "BODY", "CIRCUIT", "PUMP", "HEATER", "CHEM", "SENSE",
            "SCHED", "VALVE", "CIRCGRP", "PMPCIRC", "REMOTE", "REMBTN",
            "EXTINSTR", "FEATR", "PRESS", "SYSTEM", "SYSTIM", "PANEL",
            "MODULE", "PERMIT"
        ]

        all_discovered: dict[str, set[str]] = {}

        for objtype in object_types:
            print(f"Querying {objtype}...", end=" ", flush=True)

            # Get all objects of this type with ALL their attributes
            # by using a huge list of potential attribute names
            response = await controller.send_cmd(
                "GetParamList",
                {
                    "condition": f"OBJTYP={objtype}",
                    "objectList": [{"objnam": "INCR", "keys": [
                        # Request a massive list of potential attributes
                        "OBJTYP", "SUBTYP", "OBJNAM", "HNAME", "SNAME", "PARENT", "BODY",
                        "STATUS", "MODE", "TEMP", "LOTMP", "HITMP", "LSTTMP", "HTMODE",
                        "HTSRC", "BOOST", "READY", "STATIC", "MANUAL", "FILTER", "SELECT",
                        "CIRCUIT", "HEATER", "VOL", "LISTORD", "PRIM", "SEC", "SPEED",
                        "ACT1", "ACT2", "ACT3", "ACT4", "SHARE", "FEATR", "USE", "LIMIT",
                        "TIME", "TIMOUT", "DNTSTP", "FREEZE", "CHILD", "SWIM", "SYNC",
                        "SET", "DLY", "GPM", "RPM", "PWR", "MIN", "MAX", "MINF", "MAXF",
                        "PRIMFLO", "PRIMTIM", "PRIOR", "SETTMP", "SETTMPNC", "SYSTIM",
                        "NAME", "OBJLIST", "CALIB", "PROBE", "SOURCE", "ASSIGN",
                        "PHVAL", "PHSET", "PHHI", "PHLO", "PHTNK", "ORPVAL", "ORPSET",
                        "ORPHI", "ORPLO", "ORPTNK", "SALT", "ALK", "CALC", "CYACID",
                        "QUALTY", "SINDEX", "SUPER", "CHLOR", "COMUART",
                        "VER", "PROPNAME", "ADDRESS", "CITY", "STATE", "ZIP", "COUNTRY",
                        "EMAIL", "EMAIL2", "PHONE", "PHONE2", "LOCX", "LOCY", "PASSWRD",
                        "SERVICE", "VACFLO", "MANHT", "HEATING", "VALVE", "AVAIL",
                        "DAY", "CLK24A", "TIMZON", "DLSTIM", "SINGLE", "START", "STOP",
                        "SMTSRT", "UPDATE", "GROUP", "COOLING", "VACFLO", "VACTIM",
                        "COOL", "PERMIT", "SHOMNU", "ENABLE", "CIRCUITS", "PORT",
                        "NORMAL", "ACT",
                    ]}],
                },
            )

            discovered_attrs: set[str] = set()
            obj_count = 0

            for obj in response.get("objectList", []):
                obj_count += 1
                params = obj.get("params", {})
                for key, value in params.items():
                    # Only count if the value is different from the key
                    # (key=value means attribute doesn't exist)
                    if value != key and value is not None:
                        discovered_attrs.add(key)

            all_discovered[objtype] = discovered_attrs
            print(f"{obj_count} objects, {len(discovered_attrs)} unique attrs")

        # Now compare with what we track
        print("\n" + "=" * 70)
        print("DISCOVERY RESULTS: Attributes with real values")
        print("=" * 70)

        total_new = 0

        for objtype in sorted(all_discovered.keys()):
            discovered = all_discovered[objtype]
            tracked = ALL_ATTRIBUTES_BY_TYPE.get(objtype, set())

            # Find attributes we discovered but don't track
            new_attrs = discovered - tracked - {"OBJTYP", "HNAME", "OBJNAM"}

            if new_attrs:
                print(f"\n{objtype}: {len(new_attrs)} NEW attributes found!")
                for attr in sorted(new_attrs):
                    print(f"  + {attr}")
                total_new += len(new_attrs)

        if total_new == 0:
            print("\n✓ No new attributes discovered - we're tracking everything!")
        else:
            print(f"\nTotal: {total_new} new attributes to consider adding")

    finally:
        await controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
