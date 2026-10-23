"""Synthetic permission material must stay out of diagnostic failure paths."""

import logging
import traceback
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyintellicenter import (
    ICBaseController,
    ICModelController,
    ICResponseError,
    PoolModel,
    PoolObject,
)
from pyintellicenter.connection import ICProtocol
from tests.test_connection import _ScriptedWebSocket, _start_ws_transport

SECRET = "synthetic-passcode-105"


@pytest.mark.parametrize("key", ["PASSWRD", "passwrd", "Password", "PASSCODE"])
def test_model_representations_mask_credentials_without_mutation(key):
    nested = {"items": [{key: SECRET}], "tuple": ({key: SECRET},)}
    obj = PoolObject("permit-placeholder", {"OBJTYP": "PERMIT", key: SECRET, "nested": nested})
    assert SECRET not in str(obj)
    assert SECRET not in repr(obj)
    assert "[REDACTED]" in str(obj)
    assert obj[key] == SECRET
    assert obj["nested"] == nested


def test_malformed_model_entries_omit_payloads(caplog):
    caplog.set_level(logging.DEBUG, logger="pyintellicenter.model")
    model = PoolModel()
    entries = [
        {"params": {"PASSWRD": SECRET}},
        {"objnam": None, "params": {"PASSWRD": SECRET}},
    ]
    model.add_objects(entries)
    model.reconcile(entries)
    model.process_updates(entries)
    model.add_object("permit-placeholder", {"PASSWRD": SECRET})
    assert SECRET not in caplog.text
    assert "payload omitted" in caplog.text


def test_tcp_malformed_frames_omit_permission_material(caplog):
    protocol = ICProtocol()
    for frame in [f'[{{"PASSWRD":"{SECRET}"}}]', f'{{"PASSWRD":"{SECRET}"']:
        protocol.data_received(frame.encode() + b"\r\n")
    assert SECRET not in caplog.text
    assert "non-object JSON frame" in caplog.text
    assert "Invalid JSON" in caplog.text


async def test_websocket_malformed_frames_omit_permission_material(caplog):
    import asyncio

    ws = _ScriptedWebSocket()
    transport = _start_ws_transport(ws)
    try:
        ws.feed(f'[{{"PASSWRD":"{SECRET}"}}]')
        ws.feed(f'{{"PASSWRD":"{SECRET}"')
        await asyncio.sleep(0.01)
        assert SECRET not in caplog.text
        assert "non-object JSON frame" in caplog.text
        assert "Invalid JSON" in caplog.text
    finally:
        await transport.aclose()


@pytest.mark.parametrize(
    "response",
    [
        {"response": "200", "PASSWRD": SECRET},
        {"objectList": [{"objnam": "placeholder", "params": {"PASSWRD": SECRET}}]},
        {"objectList": [{"objnam": "placeholder", "params": SECRET}]},
        {"objectList": [SECRET]},
        {"objectList": [], "PASSWRD": SECRET},
    ],
)
async def test_malformed_system_info_exception_omits_payload(response):
    controller = ICBaseController("192.0.2.105", 6681)
    connection = AsyncMock()
    connection.connected = True
    connection.set_disconnect_callback = MagicMock()
    connection.add_notification_observer = MagicMock(return_value=MagicMock())
    connection.set_notification_callback = MagicMock()
    connection.send_request.return_value = response
    with (
        patch("pyintellicenter.controller.ICConnection", return_value=connection),
        pytest.raises(ICResponseError) as caught,
    ):
        await controller.start()
    assert caught.value.code == "MALFORMED"
    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value)
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    connection.disconnect.assert_awaited_once()


async def test_malformed_subscription_exception_omits_payload():
    controller = ICModelController("192.0.2.105", 6681)
    with (
        patch.object(controller, "send_cmd", AsyncMock(return_value={"PASSWRD": SECRET})),
        pytest.raises(ICResponseError) as caught,
    ):
        await controller._send_monitor_batch([])
    assert caught.value.code == "MALFORMED"
    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value)
    assert SECRET not in "".join(traceback.format_exception(caught.value))
