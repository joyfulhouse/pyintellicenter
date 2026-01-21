#!/usr/bin/env python3
"""Query all chemistry controller attributes from live IntelliCenter device."""

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
        print(f"Connected to: {controller.system_info.prop_name}")
        print()

        # Query ALL parameters for chemistry controllers (no filter on keys)
        # This returns everything the device knows about these objects
        print("=" * 70)
        print("Querying ALL attributes for chemistry controllers...")
        print("=" * 70)

        # Query specific chemistry controllers with a broad set of potential attributes
        # CHR01 = IntelliChlor, CHM01 = IntelliChem
        potential_keys = [
            # Standard chem attributes
            "OBJTYP", "SUBTYP", "SNAME", "HNAME", "PARENT", "BODY", "LISTORD",
            # pH related
            "PHVAL", "PHSET", "PHHI", "PHLO", "PHTNK",
            "PHCAL", "PHADJ", "PHOFS", "PHOFF", "PHCALIB",
            # ORP related
            "ORPVAL", "ORPSET", "ORPHI", "ORPLO", "ORPTNK",
            "ORPCAL", "ORPADJ", "ORPOFS", "ORPOFF", "ORPCALIB",
            # Chlorinator
            "PRIM", "SEC", "SALT", "SUPER", "TIMOUT",
            # Chemistry
            "ALK", "CALC", "CYACID", "QUALTY", "SINDEX",
            # Calibration/offset variations
            "CALIB", "CAL", "OFFSET", "OFS", "ADJ", "BIAS", "TRIM",
            "PHCAL1", "PHCAL2", "ORPCAL1", "ORPCAL2",
            # Other
            "STATUS", "MODE", "CHLOR", "COMUART", "SHARE",
            # All params
            "ACT", "AVAIL", "ENABLE", "VER", "STATIC",
        ]

        response = await controller.send_cmd(
            "GetParamList",
            {
                "objectList": [
                    {"objnam": "CHR01", "keys": potential_keys},  # IntelliChlor
                    {"objnam": "CHM01", "keys": potential_keys},  # IntelliChem
                ]
            },
        )

        for obj in response.get("objectList", []):
            objnam = obj.get("objnam")
            params = obj.get("params", {})

            print(f"\n{objnam}:")
            print("-" * 40)

            # Sort and print all parameters
            for key in sorted(params.keys()):
                value = params[key]
                print(f"  {key}: {value}")

        # Also check if there's any "calibration" or "offset" related attributes
        print("\n" + "=" * 70)
        print("Looking for calibration/offset related attributes...")
        print("=" * 70)

        for obj in response.get("objectList", []):
            params = obj.get("params", {})
            objnam = obj.get("objnam")

            for key, value in params.items():
                key_lower = key.lower()
                if any(
                    term in key_lower
                    for term in ["calib", "offset", "cal", "adj", "bias", "trim"]
                ):
                    print(f"  {objnam}.{key}: {value}")

        # Try GetHardwareDefinition to see if there are more objects
        print("\n" + "=" * 70)
        print("Checking GetHardwareDefinition for CHEM objects...")
        print("=" * 70)

        hw_response = await controller.send_cmd(
            "GetQuery",
            {"queryName": "GetHardwareDefinition", "arguments": ""},
        )

        def find_chem_objects(obj_list: list, prefix: str = "") -> None:
            """Recursively find chemistry-related objects."""
            for item in obj_list:
                if isinstance(item, dict):
                    objnam = item.get("objnam", "")
                    objtyp = item.get("params", {}).get("OBJTYP", "")
                    sname = item.get("params", {}).get("SNAME", "")

                    if objtyp == "CHEM" or "chem" in sname.lower():
                        print(f"{prefix}{objnam} ({objtyp}): {sname}")
                        # Print all params
                        for k, v in item.get("params", {}).items():
                            if v != k:  # Skip unset attrs where key==value
                                print(f"  {k}: {v}")

                    # Recurse into children
                    children = item.get("params", {}).get("OBJLIST", [])
                    if isinstance(children, list):
                        find_chem_objects(children, prefix + "  ")

        if hw_response:
            answer = hw_response.get("answer", [])
            find_chem_objects(answer)

    finally:
        await controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
