"""Transport abstractions for serial and mux connections.

Mirrors the Rust client's ``transport.rs``.  The :class:`MuxConnection`
class is a drop-in replacement for ``serial.Serial`` that talks to the
mux daemon over a Unix domain socket or TCP.
"""

from __future__ import annotations

import socket


class MuxConnection:
    """Drop-in replacement for ``serial.Serial`` that talks to the mux daemon."""

    def __init__(self, sock: socket.socket, timeout: float = 2.0) -> None:
        self._sock = sock
        self._timeout = timeout
        self._sock.settimeout(timeout)

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = value
        self._sock.settimeout(value)

    def read(self, n: int = 1) -> bytes:
        try:
            data = self._sock.recv(n)
            if not data:
                raise ConnectionError("mux disconnected")
            return data
        except TimeoutError:
            return b""

    def write(self, data: bytes) -> int:
        self._sock.sendall(data)
        return len(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self._sock.close()
