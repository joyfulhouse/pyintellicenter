"""Credential masking for human-readable model representations."""

from __future__ import annotations

from typing import Any


def _redact_credentials(value: Any) -> Any:
    """Return a diagnostic copy; raw model values remain available to callers."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if isinstance(key, str) and key.casefold() in {"passwrd", "password", "passcode"}
            else _redact_credentials(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_credentials(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_credentials(item) for item in value)
    return value
