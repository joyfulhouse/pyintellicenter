"""Exception hierarchy for pyintellicenter.

This module provides a unified exception hierarchy for all library errors,
making it easier to catch and handle specific error types.
"""

from __future__ import annotations


class ICError(Exception):
    """Base exception for all pyintellicenter errors.

    All exceptions raised by this library inherit from this class,
    making it easy to catch any library-specific error.
    """


class ICConnectionError(ICError):
    """Raised when connection fails or is lost.

    This exception is raised for network-level issues such as:
    - Failed to establish TCP connection
    - Connection timeout
    - Connection closed unexpectedly
    - Keepalive timeout
    """


class ICResponseError(ICError):
    """Raised when IntelliCenter returns an error response.

    The IntelliCenter system returns HTTP-like status codes.
    A response code other than "200" indicates an error.

    Attributes:
        code: The error code returned by IntelliCenter
        message: Optional error message
    """

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message
        super().__init__(
            f"IntelliCenter error {code}: {message}" if message else f"IntelliCenter error {code}"
        )

    def __repr__(self) -> str:
        return f"ICResponseError(code={self.code!r}, message={self.message!r})"


class ICCommandError(ICError):
    """Raised when a command to IntelliCenter fails.

    This is a higher-level exception that wraps ICResponseError
    for use at the controller layer.

    Attributes:
        error_code: The error code from the underlying response
    """

    def __init__(self, error_code: str) -> None:
        self._error_code = error_code
        super().__init__(f"IntelliCenter command error: {error_code}")

    @property
    def error_code(self) -> str:
        """Return the error code."""
        return self._error_code

    def __repr__(self) -> str:
        return f"ICCommandError(error_code={self._error_code!r})"


class ICTimeoutError(ICError):
    """Raised when a request times out waiting for a response.

    This is distinct from connection timeout - it indicates the
    connection is established but the response was not received
    within the expected time.
    """
