"""Per-modulation config dataclasses for ``SET_CONFIG`` payloads.

Mirrors the Rust crate's ``modulation`` module byte-for-byte. Users
build a :class:`LoRaConfig` (or FSK/LR-FHSS/FLRC variant) and pass it
to :meth:`donglora.dongle.Dongle.set_config` or to :func:`connect` as
an override.

The `.default()` classmethod on each returns a sensible starting point
— for LoRa that's the Appendix C.2.3 canonical EU868 config, which is
also what :func:`connect()` auto-applies.
"""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass, field

# ── Modulation ID (u8 prefix byte on every SET_CONFIG payload) ────


class ModulationId(enum.IntEnum):
    LORA = 0x01
    FSK_GFSK = 0x02
    LR_FHSS = 0x03
    FLRC = 0x04


# ── LoRa enums ─────────────────────────────────────────────────────


class LoRaBandwidth(enum.IntEnum):
    """LoRa bandwidth enum — integer is the wire value, not kHz."""

    KHZ_7_81 = 0
    KHZ_10_42 = 1
    KHZ_15_63 = 2
    KHZ_20_83 = 3
    KHZ_31_25 = 4
    KHZ_41_67 = 5
    KHZ_62_5 = 6
    KHZ_125 = 7
    KHZ_250 = 8
    KHZ_500 = 9
    KHZ_200 = 10  # SX128x
    KHZ_400 = 11  # SX128x
    KHZ_800 = 12  # SX128x
    KHZ_1600 = 13  # SX128x

    @property
    def khz(self) -> float:
        """Nominal bandwidth in kHz. Use with ``:g`` or ``:.1f`` for display."""
        return _BW_KHZ[self]


_BW_KHZ: dict[LoRaBandwidth, float] = {
    LoRaBandwidth.KHZ_7_81: 7.81,
    LoRaBandwidth.KHZ_10_42: 10.42,
    LoRaBandwidth.KHZ_15_63: 15.63,
    LoRaBandwidth.KHZ_20_83: 20.83,
    LoRaBandwidth.KHZ_31_25: 31.25,
    LoRaBandwidth.KHZ_41_67: 41.67,
    LoRaBandwidth.KHZ_62_5: 62.5,
    LoRaBandwidth.KHZ_125: 125.0,
    LoRaBandwidth.KHZ_250: 250.0,
    LoRaBandwidth.KHZ_500: 500.0,
    LoRaBandwidth.KHZ_200: 200.0,
    LoRaBandwidth.KHZ_400: 400.0,
    LoRaBandwidth.KHZ_800: 800.0,
    LoRaBandwidth.KHZ_1600: 1600.0,
}


class LoRaCodingRate(enum.IntEnum):
    CR_4_5 = 0
    CR_4_6 = 1
    CR_4_7 = 2
    CR_4_8 = 3


class LoRaHeaderMode(enum.IntEnum):
    EXPLICIT = 0
    IMPLICIT = 1


# ── LoRa config ────────────────────────────────────────────────────


@dataclass(frozen=True)
class LoRaConfig:
    """LoRa modulation parameters. 15-byte wire struct."""

    freq_hz: int
    sf: int  # 5-12
    bw: LoRaBandwidth
    cr: LoRaCodingRate
    preamble_len: int = 8
    sync_word: int = 0x1424
    tx_power_dbm: int = 14
    header_mode: LoRaHeaderMode = LoRaHeaderMode.EXPLICIT
    payload_crc: bool = True
    iq_invert: bool = False

    WIRE_SIZE: int = field(default=15, init=False, repr=False, compare=False)

    @classmethod
    def default(cls) -> LoRaConfig:
        """PROTOCOL.md §C.2.3 canonical EU868 config — also what
        :func:`donglora.connect` auto-applies.
        """
        return cls(
            freq_hz=868_100_000,
            sf=7,
            bw=LoRaBandwidth.KHZ_125,
            cr=LoRaCodingRate.CR_4_5,
            preamble_len=8,
            sync_word=0x1424,
            tx_power_dbm=14,
            header_mode=LoRaHeaderMode.EXPLICIT,
            payload_crc=True,
            iq_invert=False,
        )

    def encode(self) -> bytes:
        return (
            struct.pack("<I", self.freq_hz)
            + bytes([self.sf, int(self.bw), int(self.cr)])
            + struct.pack("<H", self.preamble_len)
            + struct.pack("<H", self.sync_word)
            + struct.pack("<b", self.tx_power_dbm)
            + bytes(
                [
                    int(self.header_mode),
                    1 if self.payload_crc else 0,
                    1 if self.iq_invert else 0,
                ],
            )
        )

    @classmethod
    def decode(cls, data: bytes) -> LoRaConfig:
        if len(data) != 15:
            raise ValueError(f"LoRaConfig wire size must be 15 bytes, got {len(data)}")
        (freq_hz,) = struct.unpack_from("<I", data, 0)
        sf = data[4]
        bw = LoRaBandwidth(data[5])
        cr = LoRaCodingRate(data[6])
        (preamble_len,) = struct.unpack_from("<H", data, 7)
        (sync_word,) = struct.unpack_from("<H", data, 9)
        (tx_power_dbm,) = struct.unpack_from("<b", data, 11)
        header_mode = LoRaHeaderMode(data[12])
        if data[13] not in (0, 1) or data[14] not in (0, 1):
            raise ValueError("LoRaConfig payload_crc / iq_invert must be 0 or 1")
        return cls(
            freq_hz=freq_hz,
            sf=sf,
            bw=bw,
            cr=cr,
            preamble_len=preamble_len,
            sync_word=sync_word,
            tx_power_dbm=tx_power_dbm,
            header_mode=header_mode,
            payload_crc=bool(data[13]),
            iq_invert=bool(data[14]),
        )


# ── FSK / GFSK config ──────────────────────────────────────────────


@dataclass(frozen=True)
class FskConfig:
    """FSK / GFSK modulation parameters. Wire size ``16 + sync_word_len``."""

    freq_hz: int
    bitrate_bps: int
    freq_dev_hz: int
    rx_bw: int  # chip-specific enum index
    preamble_len: int = 16
    sync_word: bytes = b""  # 0-8 bytes

    def encode(self) -> bytes:
        if len(self.sync_word) > 8:
            raise ValueError("FSK sync word max 8 bytes")
        return (
            struct.pack("<I", self.freq_hz)
            + struct.pack("<I", self.bitrate_bps)
            + struct.pack("<I", self.freq_dev_hz)
            + bytes([self.rx_bw])
            + struct.pack("<H", self.preamble_len)
            + bytes([len(self.sync_word)])
            + self.sync_word
        )

    @classmethod
    def decode(cls, data: bytes) -> FskConfig:
        if len(data) < 16:
            raise ValueError(f"FskConfig too short: {len(data)}")
        (freq_hz,) = struct.unpack_from("<I", data, 0)
        (bitrate_bps,) = struct.unpack_from("<I", data, 4)
        (freq_dev_hz,) = struct.unpack_from("<I", data, 8)
        rx_bw = data[12]
        (preamble_len,) = struct.unpack_from("<H", data, 13)
        sync_word_len = data[15]
        if sync_word_len > 8:
            raise ValueError(f"FSK sync_word_len out of range: {sync_word_len}")
        if len(data) != 16 + sync_word_len:
            raise ValueError(f"FskConfig wrong total length: {len(data)}")
        return cls(
            freq_hz=freq_hz,
            bitrate_bps=bitrate_bps,
            freq_dev_hz=freq_dev_hz,
            rx_bw=rx_bw,
            preamble_len=preamble_len,
            sync_word=bytes(data[16 : 16 + sync_word_len]),
        )


# ── LR-FHSS config ─────────────────────────────────────────────────


class LrFhssBandwidth(enum.IntEnum):
    KHZ_39 = 0
    KHZ_86 = 1
    KHZ_137 = 2
    KHZ_184 = 3
    KHZ_336 = 4
    KHZ_387 = 5
    KHZ_723 = 6
    KHZ_1523 = 7


class LrFhssCodingRate(enum.IntEnum):
    CR_5_6 = 0
    CR_2_3 = 1
    CR_1_2 = 2
    CR_1_3 = 3


class LrFhssGrid(enum.IntEnum):
    KHZ_25 = 0
    KHZ_3_9 = 1


@dataclass(frozen=True)
class LrFhssConfig:
    """LR-FHSS modulation parameters. 10-byte wire struct. TX-only on all
    current Semtech silicon.
    """

    freq_hz: int
    bw: LrFhssBandwidth
    cr: LrFhssCodingRate
    grid: LrFhssGrid
    hopping: bool = True
    tx_power_dbm: int = 14

    def encode(self) -> bytes:
        return (
            struct.pack("<I", self.freq_hz)
            + bytes([int(self.bw), int(self.cr), int(self.grid)])
            + bytes([1 if self.hopping else 0])
            + struct.pack("<b", self.tx_power_dbm)
            + b"\x00"  # reserved
        )

    @classmethod
    def decode(cls, data: bytes) -> LrFhssConfig:
        if len(data) != 10:
            raise ValueError(f"LrFhssConfig wire size must be 10 bytes, got {len(data)}")
        (freq_hz,) = struct.unpack_from("<I", data, 0)
        bw = LrFhssBandwidth(data[4])
        cr = LrFhssCodingRate(data[5])
        grid = LrFhssGrid(data[6])
        if data[7] not in (0, 1):
            raise ValueError("hopping must be 0 or 1")
        (tx_power_dbm,) = struct.unpack_from("<b", data, 8)
        if data[9] != 0:
            raise ValueError("LR-FHSS reserved byte must be 0")
        return cls(
            freq_hz=freq_hz,
            bw=bw,
            cr=cr,
            grid=grid,
            hopping=bool(data[7]),
            tx_power_dbm=tx_power_dbm,
        )


# ── FLRC config ────────────────────────────────────────────────────


class FlrcBitrate(enum.IntEnum):
    KBPS_2600 = 0
    KBPS_2080 = 1
    KBPS_1300 = 2
    KBPS_1040 = 3
    KBPS_650 = 4
    KBPS_520 = 5
    KBPS_325 = 6
    KBPS_260 = 7


class FlrcCodingRate(enum.IntEnum):
    CR_1_2 = 0
    CR_3_4 = 1
    CR_1_1 = 2


class FlrcBt(enum.IntEnum):
    OFF = 0
    BT_0_5 = 1
    BT_1_0 = 2


class FlrcPreambleLen(enum.IntEnum):
    BITS_8 = 0
    BITS_12 = 1
    BITS_16 = 2
    BITS_20 = 3
    BITS_24 = 4
    BITS_28 = 5
    BITS_32 = 6


@dataclass(frozen=True)
class FlrcConfig:
    """FLRC modulation parameters. 13-byte wire struct. SX128x / LR2021 only."""

    freq_hz: int
    bitrate: FlrcBitrate
    cr: FlrcCodingRate
    bt: FlrcBt
    preamble_len: FlrcPreambleLen
    sync_word: int  # 32-bit, transmitted MSB-first on air
    tx_power_dbm: int = 14

    def encode(self) -> bytes:
        return (
            struct.pack("<I", self.freq_hz)
            + bytes(
                [
                    int(self.bitrate),
                    int(self.cr),
                    int(self.bt),
                    int(self.preamble_len),
                ],
            )
            + struct.pack("<I", self.sync_word)
            + struct.pack("<b", self.tx_power_dbm)
        )

    @classmethod
    def decode(cls, data: bytes) -> FlrcConfig:
        if len(data) != 13:
            raise ValueError(f"FlrcConfig wire size must be 13 bytes, got {len(data)}")
        (freq_hz,) = struct.unpack_from("<I", data, 0)
        bitrate = FlrcBitrate(data[4])
        cr = FlrcCodingRate(data[5])
        bt = FlrcBt(data[6])
        preamble_len = FlrcPreambleLen(data[7])
        (sync_word,) = struct.unpack_from("<I", data, 8)
        (tx_power_dbm,) = struct.unpack_from("<b", data, 12)
        return cls(
            freq_hz=freq_hz,
            bitrate=bitrate,
            cr=cr,
            bt=bt,
            preamble_len=preamble_len,
            sync_word=sync_word,
            tx_power_dbm=tx_power_dbm,
        )


# ── Sum type for SET_CONFIG payloads ───────────────────────────────

Modulation = LoRaConfig | FskConfig | LrFhssConfig | FlrcConfig


def encode_modulation(mod: Modulation) -> bytes:
    """Encode a modulation-agnostic ``[modulation_id || params]`` payload."""
    if isinstance(mod, LoRaConfig):
        return bytes([ModulationId.LORA]) + mod.encode()
    if isinstance(mod, FskConfig):
        return bytes([ModulationId.FSK_GFSK]) + mod.encode()
    if isinstance(mod, LrFhssConfig):
        return bytes([ModulationId.LR_FHSS]) + mod.encode()
    if isinstance(mod, FlrcConfig):
        return bytes([ModulationId.FLRC]) + mod.encode()
    raise TypeError(f"unknown modulation type: {type(mod)}")


def decode_modulation(data: bytes) -> Modulation:
    if not data:
        raise ValueError("modulation payload is empty")
    mod_id = data[0]
    params = data[1:]
    if mod_id == ModulationId.LORA:
        return LoRaConfig.decode(params)
    if mod_id == ModulationId.FSK_GFSK:
        return FskConfig.decode(params)
    if mod_id == ModulationId.LR_FHSS:
        return LrFhssConfig.decode(params)
    if mod_id == ModulationId.FLRC:
        return FlrcConfig.decode(params)
    raise ValueError(f"unknown modulation_id: 0x{mod_id:02X}")
