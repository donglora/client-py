"""COBS framing for the DongLoRa USB protocol.

Mirrors the Rust client's ``codec.rs``.  Frames are COBS-encoded with a
``0x00`` sentinel byte.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cobs import cobs


@runtime_checkable
class Readable(Protocol):
    """Anything with a blocking ``read(n)`` method (serial port, socket wrapper, etc.)."""

    def read(self, n: int = 1) -> bytes: ...


def cobs_encode(data: bytes) -> bytes:
    """COBS-encode *data* and append the ``0x00`` sentinel."""
    return cobs.encode(data) + b"\x00"


def read_frame(reader: Readable) -> bytes | None:
    """Read one COBS frame from *reader*.

    Returns decoded payload bytes, or ``None`` on timeout (zero-length read).
    """
    buf = b""
    while True:
        b = reader.read(1)
        if not b:
            return None
        if b == b"\x00":
            break
        buf += b
    if not buf:
        return None
    try:
        return cobs.decode(buf)
    except cobs.DecodeError:
        return None
