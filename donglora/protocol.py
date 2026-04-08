"""Wire protocol types and fixed-size little-endian serialization.

Mirrors the firmware's protocol and the Rust client's ``protocol.rs``
using Python types.  Every integer is fixed-width LE.
"""

from __future__ import annotations

import enum
import struct
from typing import Any, TypedDict

# ── Size constants ────────────────────────────────────────────────

MAX_PAYLOAD: int = 256
"""Maximum LoRa payload size in bytes."""

RADIO_CONFIG_SIZE: int = 13
"""RadioConfig wire size (fixed)."""

TX_POWER_MAX: int = -128
"""Sentinel: set TX power to the board's maximum (i8::MIN on the wire)."""

PREAMBLE_DEFAULT: int = 0
"""Sentinel: use firmware default preamble length (16 symbols)."""

# ── Tag constants ─────────────────────────────────────────────────

CMD_TAG_PING: int = 0
CMD_TAG_GET_CONFIG: int = 1
CMD_TAG_SET_CONFIG: int = 2
CMD_TAG_START_RX: int = 3
CMD_TAG_STOP_RX: int = 4
CMD_TAG_TRANSMIT: int = 5
CMD_TAG_DISPLAY_ON: int = 6
CMD_TAG_DISPLAY_OFF: int = 7
CMD_TAG_GET_MAC: int = 8

RESP_TAG_PONG: int = 0
RESP_TAG_CONFIG: int = 1
RESP_TAG_RX_PACKET: int = 2
RESP_TAG_TX_DONE: int = 3
RESP_TAG_OK: int = 4
RESP_TAG_ERROR: int = 5
RESP_TAG_MAC_ADDRESS: int = 6

# ── Enums ─────────────────────────────────────────────────────────


class Bandwidth(enum.IntEnum):
    """LoRa signal bandwidth."""

    Khz7 = 0
    Khz10 = 1
    Khz15 = 2
    Khz20 = 3
    Khz31 = 4
    Khz41 = 5
    Khz62 = 6
    Khz125 = 7
    Khz250 = 8
    Khz500 = 9


class ErrorCode(enum.IntEnum):
    """Error codes reported by the firmware."""

    InvalidConfig = 0
    RadioBusy = 1
    TxTimeout = 2
    CrcError = 3
    NotConfigured = 4
    NoDisplay = 5


ERROR_INVALID_CONFIG: int = ErrorCode.InvalidConfig
ERROR_RADIO_BUSY: int = ErrorCode.RadioBusy
ERROR_TX_TIMEOUT: int = ErrorCode.TxTimeout
ERROR_NOT_CONFIGURED: int = ErrorCode.NotConfigured
ERROR_NO_DISPLAY: int = ErrorCode.NoDisplay

# ── RadioConfig ───────────────────────────────────────────────────


class RadioConfig(TypedDict):
    """Complete LoRa radio configuration.

    Wire layout (13 bytes, all little-endian)::

        [freq_hz:4] [bw:1] [sf:1] [cr:1] [sync_word:2]
        [tx_power_dbm:1] [preamble_len:2] [cad:1]
    """

    freq_hz: int
    bw: int
    sf: int
    cr: int
    sync_word: int
    tx_power_dbm: int
    preamble_len: int
    cad: int


DEFAULT_CONFIG: RadioConfig = {
    "freq_hz": 915_000_000,
    "bw": Bandwidth.Khz125,
    "sf": 7,
    "cr": 5,
    "sync_word": 0x1424,
    "tx_power_dbm": TX_POWER_MAX,
    "preamble_len": PREAMBLE_DEFAULT,
    "cad": 1,
}
"""Default radio config: 915 MHz, 125 kHz BW, SF7, CR 4/5, max power, CAD on."""

# ── Config wire encoding ──────────────────────────────────────────

_CONFIG_STRUCT = struct.Struct("<IBBBHBHB")


def encode_config(cfg: RadioConfig) -> bytes:
    """Encode a RadioConfig to 13 fixed-size LE bytes."""
    return _CONFIG_STRUCT.pack(
        cfg["freq_hz"],
        cfg["bw"],
        cfg["sf"],
        cfg["cr"],
        cfg["sync_word"],
        cfg["tx_power_dbm"] & 0xFF,
        cfg.get("preamble_len", PREAMBLE_DEFAULT),
        cfg.get("cad", 1),
    )


def decode_config(data: bytes) -> RadioConfig | None:
    """Decode a RadioConfig from 13 LE bytes.  Returns ``None`` if too short or invalid."""
    if len(data) < RADIO_CONFIG_SIZE:
        return None
    freq_hz, bw_raw, sf, cr, sync_word, _pwr_unsigned, preamble_len, cad = (
        _CONFIG_STRUCT.unpack_from(data, 0)
    )
    try:
        Bandwidth(bw_raw)
    except ValueError:
        return None
    tx_power_dbm = struct.unpack_from("<b", data, 9)[0]
    return {
        "freq_hz": freq_hz,
        "bw": bw_raw,
        "sf": sf,
        "cr": cr,
        "sync_word": sync_word,
        "tx_power_dbm": tx_power_dbm,
        "preamble_len": preamble_len,
        "cad": cad,
    }


# ── Command encoding ──────────────────────────────────────────────

_COMMAND_TAGS: dict[str, int] = {
    "Ping": CMD_TAG_PING,
    "GetConfig": CMD_TAG_GET_CONFIG,
    "SetConfig": CMD_TAG_SET_CONFIG,
    "StartRx": CMD_TAG_START_RX,
    "StopRx": CMD_TAG_STOP_RX,
    "Transmit": CMD_TAG_TRANSMIT,
    "DisplayOn": CMD_TAG_DISPLAY_ON,
    "DisplayOff": CMD_TAG_DISPLAY_OFF,
    "GetMac": CMD_TAG_GET_MAC,
}


def encode_command(cmd: str, **kwargs: Any) -> bytes:
    """Encode a command to fixed-size LE bytes.

    Raises ``ValueError`` for unknown commands or oversized payloads.
    """
    tag = _COMMAND_TAGS.get(cmd)
    if tag is None:
        raise ValueError(f"unknown command: {cmd!r}")
    out = bytes([tag])
    if cmd == "SetConfig":
        out += encode_config(kwargs["config"])
    elif cmd == "Transmit":
        config: RadioConfig | None = kwargs.get("config")
        if config is None:
            out += b"\x00"
        else:
            out += b"\x01" + encode_config(config)
        payload: bytes = kwargs["payload"]
        if len(payload) > MAX_PAYLOAD:
            raise ValueError(f"payload too large ({len(payload)} bytes, max {MAX_PAYLOAD})")
        out += struct.pack("<H", len(payload)) + payload
    return out


# ── Response decoding ─────────────────────────────────────────────


def decode_response(data: bytes) -> dict[str, Any]:
    """Decode a fixed-size LE response into a dict."""
    if not data:
        return {"type": "Empty"}
    tag = data[0]
    rest = data[1:]
    if tag == RESP_TAG_PONG:
        return {"type": "Pong"}
    if tag == RESP_TAG_CONFIG:
        cfg = decode_config(rest)
        if cfg is not None:
            return {"type": "Config", **cfg}
        return {"type": "Config", "raw": rest.hex()}
    if tag == RESP_TAG_RX_PACKET:
        if len(rest) < 6:
            return {"type": "RxPacket", "rssi": 0, "snr": 0, "payload": b""}
        rssi = struct.unpack_from("<h", rest, 0)[0]
        snr = struct.unpack_from("<h", rest, 2)[0]
        plen = struct.unpack_from("<H", rest, 4)[0]
        payload = rest[6 : 6 + plen]
        return {"type": "RxPacket", "rssi": rssi, "snr": snr, "payload": payload}
    if tag == RESP_TAG_TX_DONE:
        return {"type": "TxDone"}
    if tag == RESP_TAG_OK:
        return {"type": "Ok"}
    if tag == RESP_TAG_ERROR:
        code = rest[0] if rest else -1
        return {"type": "Error", "code": code}
    if tag == RESP_TAG_MAC_ADDRESS:
        if len(rest) >= 6:
            mac = ":".join(f"{b:02X}" for b in rest[:6])
            return {"type": "MacAddress", "mac": mac}
        return {"type": "MacAddress", "raw": rest.hex()}
    return {"type": f"Unknown({tag})"}
