"""Tests for donglora.protocol — ported from client-rs/src/protocol.rs tests."""

from __future__ import annotations

import struct

import pytest

from donglora.protocol import (
    DEFAULT_CONFIG,
    MAX_PAYLOAD,
    PREAMBLE_DEFAULT,
    RADIO_CONFIG_SIZE,
    TX_POWER_MAX,
    Bandwidth,
    ErrorCode,
    RadioConfig,
    decode_config,
    decode_response,
    encode_command,
    encode_config,
)


def _make_config() -> RadioConfig:
    return {
        "freq_hz": 915_000_000,
        "bw": Bandwidth.Khz125,
        "sf": 7,
        "cr": 5,
        "sync_word": 0x3444,
        "tx_power_dbm": 22,
        "preamble_len": 16,
        "cad": 1,
    }


# ── RadioConfig ──────────────────────────────────────────────────


class TestRadioConfig:
    def test_roundtrip(self) -> None:
        cfg = _make_config()
        encoded = encode_config(cfg)
        assert len(encoded) == RADIO_CONFIG_SIZE
        decoded = decode_config(encoded)
        assert decoded == cfg

    def test_default_roundtrip(self) -> None:
        encoded = encode_config(DEFAULT_CONFIG)
        decoded = decode_config(encoded)
        assert decoded is not None
        assert decoded["freq_hz"] == DEFAULT_CONFIG["freq_hz"]
        assert decoded["bw"] == DEFAULT_CONFIG["bw"]
        assert decoded["sf"] == DEFAULT_CONFIG["sf"]
        assert decoded["cr"] == DEFAULT_CONFIG["cr"]
        assert decoded["sync_word"] == DEFAULT_CONFIG["sync_word"]
        assert decoded["tx_power_dbm"] == DEFAULT_CONFIG["tx_power_dbm"]
        assert decoded["cad"] == DEFAULT_CONFIG["cad"]

    def test_all_bandwidths(self) -> None:
        for bw in Bandwidth:
            cfg = {**_make_config(), "bw": bw}
            encoded = encode_config(cfg)
            decoded = decode_config(encoded)
            assert decoded is not None
            assert decoded["bw"] == bw

    def test_invalid_bandwidth(self) -> None:
        buf = bytearray(encode_config(_make_config()))
        buf[4] = 255
        assert decode_config(bytes(buf)) is None

    def test_negative_power(self) -> None:
        cfg = {**_make_config(), "tx_power_dbm": TX_POWER_MAX}
        encoded = encode_config(cfg)
        decoded = decode_config(encoded)
        assert decoded is not None
        assert decoded["tx_power_dbm"] == TX_POWER_MAX

    def test_short_buffer(self) -> None:
        assert decode_config(bytes(12)) is None
        assert decode_config(b"") is None


# ── Command encoding ─────────────────────────────────────────────


class TestCommandEncoding:
    def test_simple_tags(self) -> None:
        assert encode_command("Ping") == bytes([0])
        assert encode_command("GetConfig") == bytes([1])
        assert encode_command("StartRx") == bytes([3])
        assert encode_command("StopRx") == bytes([4])
        assert encode_command("DisplayOn") == bytes([6])
        assert encode_command("DisplayOff") == bytes([7])
        assert encode_command("GetMac") == bytes([8])

    def test_set_config(self) -> None:
        cfg = _make_config()
        cmd = encode_command("SetConfig", config=cfg)
        assert cmd[0] == 2
        assert len(cmd) == 1 + RADIO_CONFIG_SIZE
        decoded = decode_config(cmd[1:])
        assert decoded == cfg

    def test_transmit_no_config(self) -> None:
        cmd = encode_command("Transmit", payload=b"hello")
        assert cmd[0] == 5
        assert cmd[1] == 0  # has_config = false
        length = struct.unpack_from("<H", cmd, 2)[0]
        assert length == 5
        assert cmd[4:] == b"hello"

    def test_transmit_with_config(self) -> None:
        cfg = _make_config()
        cmd = encode_command("Transmit", config=cfg, payload=b"test")
        assert cmd[0] == 5
        assert cmd[1] == 1  # has_config = true
        decoded = decode_config(cmd[2:])
        assert decoded == cfg
        offset = 2 + RADIO_CONFIG_SIZE
        length = struct.unpack_from("<H", cmd, offset)[0]
        assert length == 4
        assert cmd[offset + 2 :] == b"test"

    def test_transmit_empty_payload(self) -> None:
        cmd = encode_command("Transmit", payload=b"")
        assert cmd[0] == 5
        length = struct.unpack_from("<H", cmd, 2)[0]
        assert length == 0

    def test_transmit_oversized_payload(self) -> None:
        with pytest.raises(ValueError, match="payload too large"):
            encode_command("Transmit", payload=bytes(MAX_PAYLOAD + 1))

    def test_transmit_max_payload(self) -> None:
        cmd = encode_command("Transmit", payload=bytes(MAX_PAYLOAD))
        length = struct.unpack_from("<H", cmd, 2)[0]
        assert length == MAX_PAYLOAD

    def test_unknown_command(self) -> None:
        with pytest.raises(ValueError, match="unknown command"):
            encode_command("FakeCommand")


# ── Response decoding ────────────────────────────────────────────


class TestResponseDecoding:
    def test_pong(self) -> None:
        assert decode_response(bytes([0])) == {"type": "Pong"}

    def test_config(self) -> None:
        cfg = _make_config()
        resp = decode_response(bytes([1]) + encode_config(cfg))
        assert resp["type"] == "Config"
        assert resp["freq_hz"] == cfg["freq_hz"]
        assert resp["bw"] == cfg["bw"]
        assert resp["sf"] == cfg["sf"]
        assert resp["cr"] == cfg["cr"]
        assert resp["sync_word"] == cfg["sync_word"]
        assert resp["tx_power_dbm"] == cfg["tx_power_dbm"]
        assert resp["preamble_len"] == cfg["preamble_len"]
        assert resp["cad"] == cfg["cad"]

    def test_rx_packet(self) -> None:
        payload = b"data"
        data = bytes([2])
        data += struct.pack("<h", -80)
        data += struct.pack("<h", 10)
        data += struct.pack("<H", len(payload))
        data += payload
        resp = decode_response(data)
        assert resp["type"] == "RxPacket"
        assert resp["rssi"] == -80
        assert resp["snr"] == 10
        assert resp["payload"] == b"data"

    def test_rx_packet_empty(self) -> None:
        data = bytes([2])
        data += struct.pack("<h", -120)
        data += struct.pack("<h", -5)
        data += struct.pack("<H", 0)
        resp = decode_response(data)
        assert resp["type"] == "RxPacket"
        assert resp["payload"] == b""

    def test_tx_done(self) -> None:
        assert decode_response(bytes([3])) == {"type": "TxDone"}

    def test_ok(self) -> None:
        assert decode_response(bytes([4])) == {"type": "Ok"}

    def test_error_codes(self) -> None:
        for code in ErrorCode:
            resp = decode_response(bytes([5, code]))
            assert resp["type"] == "Error"
            assert resp["code"] == code

    def test_mac_address(self) -> None:
        mac_bytes = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])
        resp = decode_response(bytes([6]) + mac_bytes)
        assert resp["type"] == "MacAddress"
        assert resp["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_empty(self) -> None:
        assert decode_response(b"") == {"type": "Empty"}

    def test_unknown_tag(self) -> None:
        resp = decode_response(bytes([255]))
        assert resp["type"] == "Unknown(255)"


# ── Cross-compatibility with firmware encoding ────────────────────


class TestFirmwareCompatibility:
    def test_worked_example(self) -> None:
        """From PROTOCOL.md: 915 MHz, 125 kHz BW, SF7, CR 4/5, sync 0x1424, max power."""
        cfg: RadioConfig = {
            "freq_hz": 915_000_000,
            "bw": Bandwidth.Khz125,
            "sf": 7,
            "cr": 5,
            "sync_word": 0x1424,
            "tx_power_dbm": TX_POWER_MAX,
            "preamble_len": PREAMBLE_DEFAULT,
            "cad": 1,
        }
        cmd = encode_command("SetConfig", config=cfg)
        expected = bytes(
            [0x02, 0xC0, 0xCA, 0x89, 0x36, 0x07, 0x07, 0x05, 0x24, 0x14, 0x80, 0x00, 0x00, 0x01]
        )
        assert cmd == expected


# ── Enum coverage ────────────────────────────────────────────────


class TestEnums:
    def test_bandwidth_values(self) -> None:
        assert Bandwidth.Khz7 == 0
        assert Bandwidth.Khz500 == 9
        assert len(Bandwidth) == 10

    def test_error_code_values(self) -> None:
        assert ErrorCode.InvalidConfig == 0
        assert ErrorCode.RadioBusy == 1
        assert ErrorCode.TxTimeout == 2
        assert ErrorCode.CrcError == 3
        assert ErrorCode.NotConfigured == 4
        assert ErrorCode.NoDisplay == 5
        assert len(ErrorCode) == 6
