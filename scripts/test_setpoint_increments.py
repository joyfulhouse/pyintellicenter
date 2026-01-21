#!/usr/bin/env python3
"""Test setpoint increment validation against live IntelliCenter device."""

import asyncio
import os

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from pyintellicenter import ICModelController, PoolModel
from pyintellicenter.attributes import (
    ORPSET_ATTR,
    PHSET_ATTR,
    PRIM_ATTR,
    SEC_ATTR,
    SUBTYP_ATTR,
)


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

        # Find chemistry controllers
        chem_controllers = controller.get_chem_controllers()
        print(f"Found {len(chem_controllers)} chemistry controller(s):")
        print()

        for chem in chem_controllers:
            print(f"  {chem.objnam}: {chem.sname}")
            print(f"    Subtype: {chem[SUBTYP_ATTR]}")
            print(f"    pH Setpoint: {chem[PHSET_ATTR]}")
            print(f"    ORP Setpoint: {chem[ORPSET_ATTR]}")
            print(f"    Primary %: {chem[PRIM_ATTR]}")
            print(f"    Secondary %: {chem[SEC_ATTR]}")
            print()

        # If we have an IntelliChem controller, let's examine its current values
        # and try some test increments
        # Detect by presence of PHSET/ORPSET or name containing "IntelliChem"
        intellichem = next(
            (c for c in chem_controllers if c[PHSET_ATTR] is not None or "chem" in c.sname.lower()), None
        )

        if intellichem:
            print("=" * 60)
            print("Testing IntelliChem setpoint increments")
            print("=" * 60)

            objnam = intellichem.objnam
            original_ph = controller.get_ph_setpoint(objnam)
            original_orp = controller.get_orp_setpoint(objnam)

            print(f"\nOriginal pH setpoint: {original_ph}")
            print(f"Original ORP setpoint: {original_orp}")

            # Test pH increments
            print("\n--- Testing pH increments ---")
            if original_ph:
                # Test various pH increments
                ph_tests = [
                    (0.1, "0.1 increment"),
                    (0.05, "0.05 increment"),
                    (0.01, "0.01 increment"),
                    (0.2, "0.2 increment"),
                ]
                for inc, desc in ph_tests:
                    test_ph = round(original_ph + inc, 2)
                    if 6.0 <= test_ph <= 8.5:
                        print(f"Testing pH = {test_ph} ({desc})...")
                        try:
                            await controller.set_ph_setpoint(objnam, test_ph)
                            await asyncio.sleep(1)
                            new_ph = controller.get_ph_setpoint(objnam)
                            accepted = abs(new_ph - test_ph) < 0.001 if new_ph else False
                            print(f"  Sent: {test_ph}, Got: {new_ph} (accepted: {accepted})")
                        except Exception as e:
                            print(f"  Error: {e}")

                        # Restore original
                        await controller.set_ph_setpoint(objnam, original_ph)
                        await asyncio.sleep(0.5)

            # Test ORP increments
            print("\n--- Testing ORP increments ---")
            if original_orp:
                # Test various increments
                test_increments = [1, 5, 10, 25, 50]
                for inc in test_increments:
                    test_orp = original_orp + inc
                    if test_orp <= 900:  # Stay within range
                        print(f"Testing ORP = {test_orp} (increment by {inc})...")
                        try:
                            await controller.set_orp_setpoint(objnam, test_orp)
                            await asyncio.sleep(1)
                            new_orp = controller.get_orp_setpoint(objnam)
                            accepted = new_orp == test_orp
                            actual_change = new_orp - original_orp if new_orp else 0
                            print(
                                f"  Result: {new_orp} (accepted: {accepted}, "
                                f"actual change: {actual_change})"
                            )
                        except Exception as e:
                            print(f"  Error: {e}")

                        # Restore original
                        await controller.set_orp_setpoint(objnam, original_orp)
                        await asyncio.sleep(0.5)

        # Check IntelliChlor (detect by presence of PRIM or name containing "chlor")
        intellichlor = next(
            (c for c in chem_controllers if c[PRIM_ATTR] is not None or "chlor" in c.sname.lower()), None
        )

        if intellichlor:
            print("\n" + "=" * 60)
            print("Testing IntelliChlor output increments")
            print("=" * 60)

            objnam = intellichlor.objnam
            output = controller.get_chlorinator_output(objnam)
            original_prim = output["primary"]

            print(f"\nOriginal primary output: {original_prim}%")

            if original_prim is not None:
                # Test various increments
                test_increments = [1, 5, 10]
                for inc in test_increments:
                    test_prim = min(original_prim + inc, 100)
                    print(f"Testing primary = {test_prim}% (increment by {inc})...")
                    try:
                        await controller.set_chlorinator_output(objnam, test_prim)
                        await asyncio.sleep(1)
                        new_output = controller.get_chlorinator_output(objnam)
                        new_prim = new_output["primary"]
                        accepted = new_prim == test_prim
                        actual_change = new_prim - original_prim if new_prim else 0
                        print(
                            f"  Result: {new_prim}% (accepted: {accepted}, "
                            f"actual change: {actual_change})"
                        )
                    except Exception as e:
                        print(f"  Error: {e}")

                    # Restore original
                    await controller.set_chlorinator_output(objnam, original_prim)
                    await asyncio.sleep(0.5)

        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)

    finally:
        await controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
