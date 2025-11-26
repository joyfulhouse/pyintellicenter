"""Pytest fixtures for pyintellicenter tests."""

from typing import Any

import pytest

from pyintellicenter import (
    BODY_TYPE,
    CIRCUIT_TYPE,
    FEATR_ATTR,
    OBJTYP_ATTR,
    PUMP_TYPE,
    SNAME_ATTR,
    STATUS_ATTR,
    SUBTYP_ATTR,
    PoolModel,
    PoolObject,
)


@pytest.fixture
def pool_object_light() -> PoolObject:
    """Create a light PoolObject for testing."""
    return PoolObject(
        "LIGHT1",
        {
            OBJTYP_ATTR: CIRCUIT_TYPE,
            SUBTYP_ATTR: "INTELLI",
            SNAME_ATTR: "Pool Light",
            STATUS_ATTR: "OFF",
            "USE": "SAM",
        },
    )


@pytest.fixture
def pool_object_switch() -> PoolObject:
    """Create a switch PoolObject for testing."""
    return PoolObject(
        "CIRC01",
        {
            OBJTYP_ATTR: CIRCUIT_TYPE,
            SUBTYP_ATTR: "GENERIC",
            SNAME_ATTR: "Pool Cleaner",
            STATUS_ATTR: "OFF",
            FEATR_ATTR: "ON",
        },
    )


@pytest.fixture
def pool_object_pump() -> PoolObject:
    """Create a pump PoolObject for testing."""
    return PoolObject(
        "PUMP1",
        {
            OBJTYP_ATTR: PUMP_TYPE,
            SUBTYP_ATTR: "VSF",
            SNAME_ATTR: "Pool Pump",
            STATUS_ATTR: "4",
            "RPM": "0",
            "PWR": "0",
        },
    )


@pytest.fixture
def pool_model_data() -> list[dict[str, Any]]:
    """Return sample pool model data."""
    return [
        {
            "objnam": "LIGHT1",
            "params": {
                OBJTYP_ATTR: CIRCUIT_TYPE,
                SUBTYP_ATTR: "INTELLI",
                SNAME_ATTR: "Pool Light",
                STATUS_ATTR: "OFF",
            },
        },
        {
            "objnam": "POOL1",
            "params": {
                OBJTYP_ATTR: BODY_TYPE,
                SUBTYP_ATTR: "POOL",
                SNAME_ATTR: "Pool",
                STATUS_ATTR: "OFF",
            },
        },
        {
            "objnam": "SPA01",
            "params": {
                OBJTYP_ATTR: BODY_TYPE,
                SUBTYP_ATTR: "SPA",
                SNAME_ATTR: "Spa",
                STATUS_ATTR: "OFF",
            },
        },
        {
            "objnam": "PUMP1",
            "params": {
                OBJTYP_ATTR: PUMP_TYPE,
                SUBTYP_ATTR: "VSF",
                SNAME_ATTR: "Pool Pump",
                STATUS_ATTR: "4",
            },
        },
    ]


@pytest.fixture
def pool_model(pool_model_data: list[dict[str, Any]]) -> PoolModel:
    """Create a PoolModel populated with test data."""
    model = PoolModel()
    model.add_objects(pool_model_data)
    return model
