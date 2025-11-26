"""Type definitions for pyintellicenter.

This module provides TypedDict definitions for structured data
used throughout the library, improving type safety and IDE support.
"""

from __future__ import annotations

from typing import Any, TypedDict


class ObjectParams(TypedDict, total=False):
    """Parameters for a pool object.

    This is a partial dict since not all attributes are always present.
    """

    OBJTYP: str
    SUBTYP: str
    SNAME: str
    PARENT: str
    STATUS: str


class ObjectEntry(TypedDict):
    """An entry in an objectList response."""

    objnam: str
    params: dict[str, Any]


class ObjectListRequest(TypedDict, total=False):
    """Request structure for objectList queries."""

    objnam: str
    keys: list[str]


class NotificationMessage(TypedDict):
    """Structure of a NotifyList notification message."""

    command: str
    objectList: list[ObjectEntry]


class ResponseMessage(TypedDict, total=False):
    """Structure of a response message from IntelliCenter."""

    response: str
    command: str
    messageID: str
    objectList: list[ObjectEntry]
    answer: list[dict[str, Any]]
