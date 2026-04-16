"""``GET_INFO`` response payload + capability bitmap constants."""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass, field

MAX_MCU_UID_LEN: int = 32
MAX_RADIO_UID_LEN: int = 16


# ── Capability bits (PROTOCOL.md §9) ──────────────────────────────


class Capability:
    """Bit masks for ``Info.capability_bitmap``.

    Use like: ``if info.supports(Capability.LORA | Capability.CAD_BEFORE_TX): ...``.
    """

    # Modulations
    LORA = 1 << 0
    FSK = 1 << 1
    GFSK = 1 << 2
    LR_FHSS = 1 << 3
    FLRC = 1 << 4
    MSK = 1 << 5
    GMSK = 1 << 6
    BLE_COMPATIBLE = 1 << 7

    # Radio features
    CAD_BEFORE_TX = 1 << 16
    IQ_INVERSION = 1 << 17
    RANGING = 1 << 18
    GNSS_SCAN = 1 << 19
    WIFI_MAC_SCAN = 1 << 20
    SPECTRAL_SCAN = 1 << 21
    FULL_DUPLEX = 1 << 22

    # Protocol features
    MULTI_CLIENT = 1 << 32


# ── Radio chip IDs (PROTOCOL.md §8) ───────────────────────────────


class RadioChipId(enum.IntEnum):
    UNKNOWN = 0x0000
    SX1261 = 0x0001
    SX1262 = 0x0002
    SX1268 = 0x0003
    LLCC68 = 0x0004
    SX1272 = 0x0010
    SX1276 = 0x0011
    SX1277 = 0x0012
    SX1278 = 0x0013
    SX1279 = 0x0014
    SX1280 = 0x0020
    SX1281 = 0x0021
    LR1110 = 0x0030
    LR1120 = 0x0031
    LR1121 = 0x0032
    LR2021 = 0x0040


# ── Info struct ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Info:
    """``GET_INFO`` response payload. Stable for the lifetime of a session."""

    proto_major: int
    proto_minor: int
    fw_major: int
    fw_minor: int
    fw_patch: int
    radio_chip_id: int
    capability_bitmap: int
    supported_sf_bitmap: int
    supported_bw_bitmap: int
    max_payload_bytes: int
    rx_queue_capacity: int
    tx_queue_capacity: int
    freq_min_hz: int
    freq_max_hz: int
    tx_power_min_dbm: int
    tx_power_max_dbm: int
    mcu_uid: bytes
    radio_uid: bytes

    MIN_WIRE_SIZE: int = field(default=37, init=False, repr=False, compare=False)

    @property
    def chip(self) -> RadioChipId | int:
        """Project ``radio_chip_id`` into the :class:`RadioChipId` enum if
        recognised; otherwise return the raw u16 so nothing is lost for
        forward-compat with future chips.
        """
        try:
            return RadioChipId(self.radio_chip_id)
        except ValueError:
            return self.radio_chip_id

    def supports(self, mask: int) -> bool:
        """Return True if all bits in *mask* are set in the capability bitmap."""
        return (self.capability_bitmap & mask) == mask

    def supported_sf(self) -> list[int]:
        """List of spreading factors (5..12) the device supports."""
        return [sf for sf in range(16) if self.supported_sf_bitmap & (1 << sf)]

    def encode(self) -> bytes:
        if len(self.mcu_uid) > MAX_MCU_UID_LEN:
            raise ValueError(f"mcu_uid too long: {len(self.mcu_uid)}")
        if len(self.radio_uid) > MAX_RADIO_UID_LEN:
            raise ValueError(f"radio_uid too long: {len(self.radio_uid)}")
        header = struct.pack(
            "<BBBBBHQHHHHHIIbbB",
            self.proto_major,
            self.proto_minor,
            self.fw_major,
            self.fw_minor,
            self.fw_patch,
            self.radio_chip_id,
            self.capability_bitmap,
            self.supported_sf_bitmap,
            self.supported_bw_bitmap,
            self.max_payload_bytes,
            self.rx_queue_capacity,
            self.tx_queue_capacity,
            self.freq_min_hz,
            self.freq_max_hz,
            self.tx_power_min_dbm,
            self.tx_power_max_dbm,
            len(self.mcu_uid),
        )
        return header + self.mcu_uid + bytes([len(self.radio_uid)]) + self.radio_uid

    @classmethod
    def decode(cls, data: bytes) -> Info:
        if len(data) < 37:
            raise ValueError(f"Info payload too short: {len(data)}")
        (
            proto_major,
            proto_minor,
            fw_major,
            fw_minor,
            fw_patch,
            radio_chip_id,
            capability_bitmap,
            supported_sf_bitmap,
            supported_bw_bitmap,
            max_payload_bytes,
            rx_queue_capacity,
            tx_queue_capacity,
            freq_min_hz,
            freq_max_hz,
            tx_power_min_dbm,
            tx_power_max_dbm,
            mcu_uid_len,
        ) = struct.unpack_from("<BBBBBHQHHHHHIIbbB", data, 0)
        if mcu_uid_len > MAX_MCU_UID_LEN:
            raise ValueError(f"mcu_uid_len out of range: {mcu_uid_len}")
        if len(data) < 36 + mcu_uid_len + 1:
            raise ValueError(f"Info payload truncated after mcu_uid: {len(data)}")
        mcu_uid = bytes(data[36 : 36 + mcu_uid_len])
        radio_len_idx = 36 + mcu_uid_len
        radio_uid_len = data[radio_len_idx]
        if radio_uid_len > MAX_RADIO_UID_LEN:
            raise ValueError(f"radio_uid_len out of range: {radio_uid_len}")
        radio_start = radio_len_idx + 1
        if len(data) < radio_start + radio_uid_len:
            raise ValueError(f"Info payload truncated after radio_uid: {len(data)}")
        radio_uid = bytes(data[radio_start : radio_start + radio_uid_len])
        return cls(
            proto_major=proto_major,
            proto_minor=proto_minor,
            fw_major=fw_major,
            fw_minor=fw_minor,
            fw_patch=fw_patch,
            radio_chip_id=radio_chip_id,
            capability_bitmap=capability_bitmap,
            supported_sf_bitmap=supported_sf_bitmap,
            supported_bw_bitmap=supported_bw_bitmap,
            max_payload_bytes=max_payload_bytes,
            rx_queue_capacity=rx_queue_capacity,
            tx_queue_capacity=tx_queue_capacity,
            freq_min_hz=freq_min_hz,
            freq_max_hz=freq_max_hz,
            tx_power_min_dbm=tx_power_min_dbm,
            tx_power_max_dbm=tx_power_max_dbm,
            mcu_uid=mcu_uid,
            radio_uid=radio_uid,
        )
