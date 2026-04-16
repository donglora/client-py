"""Device-to-host message payloads: ``OK`` / ``ERR`` / ``RX`` / ``TX_DONE``."""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass

from donglora.errors import ErrorCode
from donglora.info import Info
from donglora.modulation import Modulation, decode_modulation, encode_modulation

# Message type identifiers
TYPE_OK: int = 0x80
TYPE_ERR: int = 0x81
TYPE_RX: int = 0xC0
TYPE_TX_DONE: int = 0xC1


# ── SET_CONFIG response payload ────────────────────────────────────


class SetConfigResultCode(enum.IntEnum):
    APPLIED = 0
    ALREADY_MATCHED = 1
    LOCKED_MISMATCH = 2


class Owner(enum.IntEnum):
    NONE = 0
    MINE = 1
    OTHER = 2


@dataclass(frozen=True)
class SetConfigResult:
    result: SetConfigResultCode
    owner: Owner
    current: Modulation

    def encode(self) -> bytes:
        return bytes([int(self.result), int(self.owner)]) + encode_modulation(self.current)

    @classmethod
    def decode(cls, data: bytes) -> SetConfigResult:
        if len(data) < 2:
            raise ValueError("SetConfigResult too short")
        return cls(
            result=SetConfigResultCode(data[0]),
            owner=Owner(data[1]),
            current=decode_modulation(data[2:]),
        )


# ── TX_DONE payload ────────────────────────────────────────────────


class TxResult(enum.IntEnum):
    TRANSMITTED = 0
    CHANNEL_BUSY = 1
    CANCELLED = 2


@dataclass(frozen=True)
class TxDone:
    result: TxResult
    airtime_us: int

    def encode(self) -> bytes:
        return bytes([int(self.result)]) + struct.pack("<I", self.airtime_us)

    @classmethod
    def decode(cls, data: bytes) -> TxDone:
        if len(data) != 5:
            raise ValueError(f"TxDone wire size must be 5, got {len(data)}")
        result = TxResult(data[0])
        (airtime_us,) = struct.unpack_from("<I", data, 1)
        return cls(result=result, airtime_us=airtime_us)


# ── RX event payload ───────────────────────────────────────────────


class RxOrigin(enum.IntEnum):
    OTA = 0
    LOCAL_LOOPBACK = 1


@dataclass(frozen=True)
class RxEvent:
    """Rich over-the-air packet metadata + the received bytes.

    ``rssi_dbm`` and ``snr_db`` are exposed as floats (converted from
    the wire's tenths-of-dB representation) so user code reads like
    ``pkt.rssi_dbm`` instead of having to divide by 10.
    """

    rssi_dbm: float
    snr_db: float
    freq_err_hz: int
    timestamp_us: int
    crc_valid: bool
    packets_dropped: int
    origin: RxOrigin
    data: bytes

    METADATA_SIZE: int = 20

    def encode(self) -> bytes:
        return (
            struct.pack("<h", round(self.rssi_dbm * 10))
            + struct.pack("<h", round(self.snr_db * 10))
            + struct.pack("<i", self.freq_err_hz)
            + struct.pack("<Q", self.timestamp_us)
            + bytes([1 if self.crc_valid else 0])
            + struct.pack("<H", self.packets_dropped)
            + bytes([int(self.origin)])
            + self.data
        )

    @classmethod
    def decode(cls, data: bytes) -> RxEvent:
        if len(data) < cls.METADATA_SIZE:
            raise ValueError(f"RxEvent payload too short: {len(data)}")
        (rssi_raw,) = struct.unpack_from("<h", data, 0)
        (snr_raw,) = struct.unpack_from("<h", data, 2)
        (freq_err_hz,) = struct.unpack_from("<i", data, 4)
        (timestamp_us,) = struct.unpack_from("<Q", data, 8)
        if data[16] not in (0, 1):
            raise ValueError("crc_valid must be 0 or 1")
        (packets_dropped,) = struct.unpack_from("<H", data, 17)
        origin = RxOrigin(data[19])
        return cls(
            rssi_dbm=rssi_raw / 10.0,
            snr_db=snr_raw / 10.0,
            freq_err_hz=freq_err_hz,
            timestamp_us=timestamp_us,
            crc_valid=bool(data[16]),
            packets_dropped=packets_dropped,
            origin=origin,
            data=bytes(data[cls.METADATA_SIZE :]),
        )


# ── OK payload helpers (context-dependent shape) ──────────────────

# Import command type IDs lazily inside functions to avoid cycles.


def parse_ok_payload(originating_cmd_type: int, payload: bytes):
    """Parse the payload of an ``OK`` frame given the type of the
    originating H→D command. Returns:

    - ``None`` for ``PING`` / ``TX`` / ``RX_START`` / ``RX_STOP`` (empty payload)
    - an :class:`Info` for ``GET_INFO``
    - a :class:`SetConfigResult` for ``SET_CONFIG``
    """
    from donglora.commands import (
        TYPE_GET_INFO,
        TYPE_PING,
        TYPE_RX_START,
        TYPE_RX_STOP,
        TYPE_SET_CONFIG,
        TYPE_TX,
    )

    if originating_cmd_type in (TYPE_PING, TYPE_TX, TYPE_RX_START, TYPE_RX_STOP):
        if payload:
            raise ValueError(f"expected empty OK payload for cmd 0x{originating_cmd_type:02X}")
        return None
    if originating_cmd_type == TYPE_GET_INFO:
        return Info.decode(payload)
    if originating_cmd_type == TYPE_SET_CONFIG:
        return SetConfigResult.decode(payload)
    raise ValueError(f"no OK shape for originating cmd 0x{originating_cmd_type:02X}")


def encode_err_payload(code: ErrorCode | int) -> bytes:
    return struct.pack("<H", int(code))


def decode_err_payload(data: bytes) -> ErrorCode | int:
    if len(data) != 2:
        raise ValueError(f"ERR payload must be 2 bytes, got {len(data)}")
    (raw,) = struct.unpack_from("<H", data, 0)
    return ErrorCode.from_u16(raw)
