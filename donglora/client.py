"""High-level DongLoRa client helpers.

Mirrors the Rust client's ``client.rs``.  Provides :func:`send`,
:func:`recv`, :func:`drain_rx`, and :func:`validate` as module-level
functions that operate on any transport (serial port or mux connection).
"""

from __future__ import annotations

import collections
from typing import Any

from donglora.codec import cobs_encode, read_frame
from donglora.protocol import decode_response, encode_command

RX_BUFFER_CAP: int = 256
"""Maximum number of buffered RxPackets before oldest are dropped."""

MAX_UNSOLICITED_BEFORE_TIMEOUT: int = 50
"""Safety bound: max frames to read while waiting for a solicited response."""

HANDSHAKE_TIMEOUT: float = 0.2
"""Timeout (seconds) for the ping-on-connect handshake."""

_rx_queue: collections.deque[dict[str, Any]] = collections.deque(maxlen=RX_BUFFER_CAP)
"""Buffer for RxPacket frames encountered while waiting for solicited responses."""


def validate(ser: Any) -> None:
    """Ping the device and verify the Pong response.

    Uses a short timeout to fail fast on non-DongLoRa devices.  Called
    automatically by the ``connect`` family of functions.

    Raises :class:`ConnectionError` if the device does not respond.
    """
    saved = ser.timeout
    ser.timeout = HANDSHAKE_TIMEOUT
    try:
        resp = send(ser, "Ping")
        if resp["type"] != "Pong":
            raise ConnectionError(f"device did not respond to ping — got {resp['type']}")
    except ConnectionError:
        raise
    except Exception as exc:
        raise ConnectionError("device did not respond to ping — not a DongLoRa device") from exc
    finally:
        ser.timeout = saved


def send(ser: Any, cmd: str, **kwargs: Any) -> dict[str, Any]:
    """Send a command and return the solicited response.

    Any unsolicited ``RxPacket`` frames encountered while waiting are
    buffered in the module-level receive queue (retrievable via
    :func:`recv` / :func:`drain_rx`).
    """
    ser.write(cobs_encode(encode_command(cmd, **kwargs)))
    ser.flush()
    for _ in range(MAX_UNSOLICITED_BEFORE_TIMEOUT):
        data = read_frame(ser)
        if data is None:
            return {"type": "Timeout"}
        resp = decode_response(data)
        if resp["type"] == "RxPacket":
            _rx_queue.append(resp)
            continue
        return resp
    return {"type": "Timeout"}


def recv(ser: Any) -> dict[str, Any] | None:
    """Return the next RxPacket from the buffer or the wire.

    Returns ``None`` on timeout (no packet available).
    """
    if _rx_queue:
        return _rx_queue.popleft()
    data = read_frame(ser)
    if data is None:
        return None
    resp = decode_response(data)
    if resp["type"] == "RxPacket":
        return resp
    return None


def drain_rx(ser: Any) -> list[dict[str, Any]]:
    """Drain all buffered and pending RxPacket frames.

    Temporarily reduces the read timeout to quickly drain any frames
    still in flight, then restores the original timeout.
    """
    packets: list[dict[str, Any]] = list(_rx_queue)
    _rx_queue.clear()
    old_timeout = ser.timeout
    ser.timeout = 0.01
    try:
        while True:
            data = read_frame(ser)
            if data is None:
                break
            resp = decode_response(data)
            if resp["type"] == "RxPacket":
                packets.append(resp)
    finally:
        ser.timeout = old_timeout
    return packets
