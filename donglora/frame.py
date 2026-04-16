"""DongLoRa Protocol frame encode/decode: ``COBS(type || tag_le || payload || crc_le) || 0x00``.

This module owns the wire-level codec. Nothing protocol-semantic lives
here; higher-level modules parse the ``(type_id, tag, payload)`` tuple
into typed commands / events.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cobs import cobs

from donglora.crc import crc16

# ── Size constants (kept in lockstep with the Rust crate) ───────────

MAX_OTA_PAYLOAD: int = 255
"""Maximum over-the-air LoRa packet payload. Chip-dependent per
PROTOCOL.md §6.2; 255 is the ceiling for all currently-supported
Semtech silicon."""

MAX_PAYLOAD_FIELD: int = MAX_OTA_PAYLOAD + 20
"""Maximum DongLoRa Protocol frame payload-field size. The ``+20`` accounts for the
RX event's fixed metadata prefix."""

FRAME_HEADER_SIZE: int = 3  # type(1) + tag(2)
FRAME_TRAILER_SIZE: int = 2  # crc16(2)
MAX_PRE_COBS_FRAME: int = FRAME_HEADER_SIZE + MAX_PAYLOAD_FIELD + FRAME_TRAILER_SIZE
MAX_COBS_OVERHEAD: int = 3  # ceil(280 / 254) + 1
MAX_WIRE_FRAME: int = MAX_PRE_COBS_FRAME + MAX_COBS_OVERHEAD + 1


# ── Frame encoding ─────────────────────────────────────────────────


class FrameTooLargeError(ValueError):
    """Payload exceeds ``MAX_PAYLOAD_FIELD``."""


def encode_frame(type_id: int, tag: int, payload: bytes) -> bytes:
    """Encode a complete wire-ready DongLoRa Protocol frame.

    Returns ``COBS(type || tag_le || payload || crc_le) || 0x00``.
    """
    if not (0 <= type_id <= 0xFF):
        raise ValueError(f"type_id out of range: {type_id}")
    if not (0 <= tag <= 0xFFFF):
        raise ValueError(f"tag out of range: {tag}")
    if len(payload) > MAX_PAYLOAD_FIELD:
        raise FrameTooLargeError(f"payload too large ({len(payload)} > {MAX_PAYLOAD_FIELD})")
    body = struct.pack("<BH", type_id, tag) + payload
    crc = crc16(body)
    pre_cobs = body + struct.pack("<H", crc)
    return cobs.encode(pre_cobs) + b"\x00"


# ── Decoded-frame result ───────────────────────────────────────────


@dataclass(frozen=True)
class Frame:
    """A successfully-decoded DongLoRa Protocol frame."""

    type_id: int
    tag: int
    payload: bytes


class FrameError(Exception):
    """A frame failed COBS, CRC, or minimum-length validation."""


class FrameCrcError(FrameError):
    """CRC trailer didn't match the computed CRC over ``type || tag || payload``."""


class FrameCobsError(FrameError):
    """COBS decode failed on the bytes before the ``0x00`` delimiter."""


class FrameTooShortError(FrameError):
    """Decoded frame was smaller than the 5-byte minimum."""


def decode_frame(frame_bytes: bytes) -> Frame:
    """Decode a single COBS+sentinel-terminated DongLoRa Protocol frame.

    *frame_bytes* must NOT include the trailing ``0x00``.
    """
    try:
        decoded = cobs.decode(frame_bytes)
    except cobs.DecodeError as exc:
        raise FrameCobsError(str(exc)) from exc
    if len(decoded) < FRAME_HEADER_SIZE + FRAME_TRAILER_SIZE:
        raise FrameTooShortError(f"decoded frame too short: {len(decoded)} bytes")
    body, crc_bytes = decoded[:-FRAME_TRAILER_SIZE], decoded[-FRAME_TRAILER_SIZE:]
    expected = crc16(body)
    (got,) = struct.unpack("<H", crc_bytes)
    if expected != got:
        raise FrameCrcError(f"CRC mismatch: got 0x{got:04X}, expected 0x{expected:04X}")
    type_id = body[0]
    (tag,) = struct.unpack_from("<H", body, 1)
    payload = body[FRAME_HEADER_SIZE:]
    return Frame(type_id=type_id, tag=tag, payload=payload)


# ── Streaming reader ───────────────────────────────────────────────


@runtime_checkable
class Readable(Protocol):
    """Anything with a blocking ``read(n)`` method — serial port, socket, etc."""

    def read(self, n: int = 1) -> bytes: ...


def read_frame(reader: Readable) -> Frame | None:
    """Block on *reader* until a full COBS-delimited frame arrives.

    Returns the decoded :class:`Frame`, or ``None`` on transport timeout.
    Raises :class:`FrameError` on CRC/COBS/length failure so the caller
    can distinguish corruption from timeout.
    """
    buf = bytearray()
    while True:
        b = reader.read(1)
        if not b:
            return None
        if b == b"\x00":
            if not buf:
                return None
            return decode_frame(bytes(buf))
        buf.extend(b)


def iter_frames(data: bytes) -> Iterator[Frame]:
    """Yield each complete frame embedded in *data* (for tests / replay).

    Raises :class:`FrameError` on the first corrupt frame encountered.
    """
    start = 0
    for i, byte in enumerate(data):
        if byte == 0x00:
            if i > start:
                yield decode_frame(bytes(data[start:i]))
            start = i + 1
