#!/usr/bin/env python3
"""Live integration test for IntelliCenter discovery.

This script tests mDNS discovery against real hardware on the network.
It auto-detects the subnet from the .env configuration.
"""

import asyncio
import ipaddress
import os
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from pyintellicenter.discovery import (
    discover_intellicenter_units,
    find_unit_by_host,
    find_unit_by_name,
)


def get_subnet_from_host(host: str) -> str:
    """Extract subnet (first 3 octets) from host IP."""
    ip = ipaddress.ip_address(host)
    if isinstance(ip, ipaddress.IPv4Address):
        octets = str(ip).split(".")
        return f"{octets[0]}.{octets[1]}.{octets[2]}.0/24"
    return str(ip)


async def test_discovery() -> bool:
    """Run live discovery test."""
    # Load environment
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        print(f"❌ .env file not found at {env_path}")
        return False

    load_dotenv(env_path)

    host = os.getenv("INTELLICENTER_HOST")
    port = int(os.getenv("INTELLICENTER_PORT", "6681"))

    if not host:
        print("❌ INTELLICENTER_HOST not set in .env")
        return False

    subnet = get_subnet_from_host(host)
    print(f"🔍 Testing discovery on subnet: {subnet}")
    print(f"📍 Expected IntelliCenter at: {host}:{port}")
    print()

    # Run discovery
    print("⏳ Running mDNS discovery (10 second timeout)...")
    units = await discover_intellicenter_units(discovery_timeout=10.0)

    if not units:
        print("❌ No IntelliCenter units discovered!")
        print()
        print("Troubleshooting tips:")
        print("  1. Ensure IntelliCenter is powered on and connected to network")
        print("  2. Verify mDNS/Bonjour is not blocked by firewall")
        print("  3. Check that you're on the same network/VLAN")
        print(f"  4. Try direct connection to {host}:{port}")
        return False

    print(f"✅ Discovered {len(units)} unit(s):")
    print()

    found_expected = False
    for unit in units:
        marker = "→" if unit.host == host else " "
        print(f"  {marker} {unit.name}")
        print(f"      Host: {unit.host}")
        print(f"      TCP Port: {unit.port} (raw protocol)")
        print(f"      WS Port: {unit.ws_port} (websocket)")
        if unit.model:
            print(f"      Model: {unit.model}")
        print()

        if unit.host == host:
            found_expected = True

    # Test find_unit_by_host
    print("🔍 Testing find_unit_by_host()...")
    unit_by_host = await find_unit_by_host(host, discovery_timeout=5.0)
    if unit_by_host:
        print(f"  ✅ Found unit by host: {unit_by_host.name}")
    else:
        print(f"  ❌ Could not find unit by host: {host}")

    # Test find_unit_by_name if we found any units
    if units:
        test_name = units[0].name
        print(f"🔍 Testing find_unit_by_name('{test_name}')...")
        unit_by_name = await find_unit_by_name(test_name, discovery_timeout=5.0)
        if unit_by_name:
            print(f"  ✅ Found unit by name: {unit_by_name.host}")
        else:
            print(f"  ❌ Could not find unit by name: {test_name}")

    print()
    if found_expected:
        print(f"✅ SUCCESS: Found expected IntelliCenter at {host}")
        return True
    else:
        print(f"⚠️  WARNING: Expected IntelliCenter at {host} not found in discovery")
        print("    The unit may not be advertising via mDNS")
        return False


async def test_direct_connection() -> bool:
    """Test direct TCP connection to the IntelliCenter."""
    from pyintellicenter import ICModelController
    from pyintellicenter.exceptions import ICConnectionError
    from pyintellicenter.model import PoolModel

    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)

    host = os.getenv("INTELLICENTER_HOST")
    port = int(os.getenv("INTELLICENTER_PORT", "6681"))

    if not host:
        print("❌ INTELLICENTER_HOST not set")
        return False

    print(f"🔌 Testing direct connection to {host}:{port}...")

    try:
        model = PoolModel()
        controller = ICModelController(host, model, port=port)
        await controller.start()

        # Get system info
        system_info = controller.system_info
        if system_info:
            print("  ✅ Connected successfully!")
            print(f"      System: {system_info.prop_name}")
            print(f"      Version: {system_info.sw_version}")
        else:
            print("  ✅ Connected (no system info available)")

        await controller.stop()
        return True

    except (OSError, TimeoutError, ICConnectionError) as e:
        print(f"  ❌ Connection failed: {e}")
        return False


async def main() -> int:
    """Run all live tests."""
    print("=" * 60)
    print("PyIntelliCenter Live Discovery Test")
    print("=" * 60)
    print()

    discovery_ok = await test_discovery()
    print()
    print("-" * 60)
    print()
    connection_ok = await test_direct_connection()

    print()
    print("=" * 60)
    print("Summary:")
    print(f"  Discovery: {'✅ PASS' if discovery_ok else '❌ FAIL'}")
    print(f"  Direct Connection: {'✅ PASS' if connection_ok else '❌ FAIL'}")
    print("=" * 60)

    return 0 if (discovery_ok and connection_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
