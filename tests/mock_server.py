"""Mock IntelliCenter server for integration testing.

This module provides a mock TCP server that simulates the IntelliCenter
protocol for integration testing purposes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import orjson

_LOGGER = logging.getLogger(__name__)


class MockIntelliCenterServer:
    """Mock IntelliCenter server for testing.

    This server simulates the IntelliCenter protocol:
    - Accepts TCP connections
    - Receives JSON messages terminated by newline
    - Responds with JSON messages
    - Can send notifications

    Example:
        async with MockIntelliCenterServer() as server:
            # Configure responses
            server.set_system_info("Test Pool", "1.0.0")
            server.add_object("POOL1", "BODY", "POOL", "Pool")

            # Run tests against server.host:server.port
            ...
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        """Initialize mock server.

        Args:
            host: Host to bind to (default: localhost)
            port: Port to bind to (0 = auto-assign)
        """
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None
        self._clients: list[asyncio.StreamWriter] = []

        # Server state
        self._objects: dict[str, dict[str, Any]] = {}
        self._system_info = {
            "PROPNAME": "Mock Pool",
            "VER": "1.0.0",
            "MODE": "ENGLISH",
            "SNAME": "MockSystem",
        }

        # Request handlers
        self._handlers: dict[str, Any] = {
            "PING": self._handle_ping,
            "GetParamList": self._handle_get_param_list,
            "RequestParamList": self._handle_request_param_list,
            "SETPARAMLIST": self._handle_set_param_list,
            "GetQuery": self._handle_get_query,
        }

    @property
    def host(self) -> str:
        """Return the server host."""
        return self._host

    @property
    def port(self) -> int:
        """Return the actual bound port."""
        if self._server:
            sockets = self._server.sockets
            if sockets:
                return sockets[0].getsockname()[1]
        return self._port

    async def start(self) -> None:
        """Start the mock server."""
        self._server = await asyncio.start_server(
            self._handle_client,
            self._host,
            self._port,
        )
        _LOGGER.info("Mock server started on %s:%d", self._host, self.port)

    async def stop(self) -> None:
        """Stop the mock server."""
        # Close all client connections
        for writer in self._clients:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        self._clients.clear()

        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def __aenter__(self) -> MockIntelliCenterServer:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()

    def set_system_info(
        self,
        name: str,
        version: str,
        mode: str = "ENGLISH",
        sname: str | None = None,
    ) -> None:
        """Configure system information."""
        self._system_info = {
            "PROPNAME": name,
            "VER": version,
            "MODE": mode,
            "SNAME": sname or name,
        }

    def add_object(
        self,
        objnam: str,
        objtyp: str,
        subtyp: str,
        sname: str,
        parent: str = "INCR",
        **extra: Any,
    ) -> None:
        """Add an object to the mock server state."""
        self._objects[objnam] = {
            "objnam": objnam,
            "OBJTYP": objtyp,
            "SUBTYP": subtyp,
            "SNAME": sname,
            "PARENT": parent,
            **extra,
        }

    def update_object(self, objnam: str, **updates: Any) -> None:
        """Update an object's attributes."""
        if objnam in self._objects:
            self._objects[objnam].update(updates)

    def get_object(self, objnam: str) -> dict[str, Any] | None:
        """Get an object by name."""
        return self._objects.get(objnam)

    async def send_notification(self, object_list: list[dict[str, Any]]) -> None:
        """Send a NotifyList notification to all connected clients."""
        msg = {
            "command": "NotifyList",
            "objectList": object_list,
        }
        await self._broadcast(msg)

    async def _broadcast(self, msg: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        data = orjson.dumps(msg) + b"\r\n"
        for writer in self._clients[:]:  # Copy list to avoid modification during iteration
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                _LOGGER.exception("Error broadcasting to client")
                self._clients.remove(writer)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        self._clients.append(writer)
        _LOGGER.info("Client connected")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    msg = orjson.loads(line)
                    response = await self._process_message(msg)
                    if response:
                        writer.write(orjson.dumps(response) + b"\r\n")
                        await writer.drain()
                except orjson.JSONDecodeError:
                    _LOGGER.error("Invalid JSON received: %s", line)
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOGGER.exception("Error handling client")
        finally:
            if writer in self._clients:
                self._clients.remove(writer)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            _LOGGER.info("Client disconnected")

    async def _process_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """Process a message and return response."""
        command = msg.get("command")
        message_id = msg.get("messageID")

        handler = self._handlers.get(command)
        if handler:
            response = await handler(msg)
            response["messageID"] = message_id
            return response

        # Unknown command
        return {
            "messageID": message_id,
            "response": "400",
            "error": f"Unknown command: {command}",
        }

    async def _handle_ping(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Handle PING request."""
        return {"response": "200"}

    async def _handle_get_param_list(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Handle GetParamList request."""
        condition = msg.get("condition", "")
        object_list = msg.get("objectList", [])

        # Check if querying for system info
        if "OBJTYP=SYSTEM" in condition:
            return {
                "response": "200",
                "objectList": [
                    {
                        "objnam": "INCR",
                        "params": self._system_info,
                    }
                ],
            }

        # Query all objects or specific objects
        result_list = []
        for req in object_list:
            if req.get("objnam") == "INCR":
                # Return all objects
                for objnam, obj in self._objects.items():
                    keys = req.get("keys", [])
                    params = {
                        k: v for k, v in obj.items() if k != "objnam" and (not keys or k in keys)
                    }
                    result_list.append({"objnam": objnam, "params": params})
            elif req.get("objnam") in self._objects:
                obj = self._objects[req["objnam"]]
                keys = req.get("keys", [])
                params = {k: v for k, v in obj.items() if k != "objnam" and (not keys or k in keys)}
                result_list.append({"objnam": req["objnam"], "params": params})

        return {"response": "200", "objectList": result_list}

    async def _handle_request_param_list(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Handle RequestParamList request (subscribe to updates)."""
        object_list = msg.get("objectList", [])

        result_list = []
        for req in object_list:
            objnam = req.get("objnam")
            if objnam in self._objects:
                obj = self._objects[objnam]
                keys = req.get("keys", [])
                params = {k: v for k, v in obj.items() if k != "objnam" and (not keys or k in keys)}
                result_list.append({"objnam": objnam, "params": params})

        return {"response": "200", "objectList": result_list}

    async def _handle_set_param_list(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Handle SETPARAMLIST request (set object parameters)."""
        object_list = msg.get("objectList", [])

        for req in object_list:
            objnam = req.get("objnam")
            params = req.get("params", {})
            if objnam in self._objects:
                self._objects[objnam].update(params)

        return {"response": "200", "objectList": object_list}

    async def _handle_get_query(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Handle GetQuery request."""
        query_name = msg.get("queryName", "")
        # Return empty answer for now
        return {"response": "200", "queryName": query_name, "answer": []}
