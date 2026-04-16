"""Event payload tests: Info, SetConfigResult, TxDone, RxEvent, ERR."""

import pytest

from donglora.commands import TYPE_PING, TYPE_SET_CONFIG
from donglora.errors import ErrorCode
from donglora.events import (
    Owner,
    RxEvent,
    RxOrigin,
    SetConfigResult,
    SetConfigResultCode,
    TxDone,
    TxResult,
    decode_err_payload,
    encode_err_payload,
    parse_ok_payload,
)
from donglora.info import Capability, Info, RadioChipId
from donglora.modulation import LoRaConfig

# ── SetConfigResult ───────────────────────────────────────────


def test_set_config_result_c23_bytes():
    # PROTOCOL.md §C.2.3: OK in reply to SET_CONFIG, LoRa applied.
    r = SetConfigResult(
        result=SetConfigResultCode.APPLIED,
        owner=Owner.MINE,
        current=LoRaConfig.default(),
    )
    expected = bytes(
        [
            0x00,
            0x01,  # result=APPLIED, owner=MINE
            0x01,  # modulation_id = LoRa
            0xA0,
            0x27,
            0xBE,
            0x33,  # freq
            0x07,
            0x07,
            0x00,  # sf / bw / cr
            0x08,
            0x00,  # preamble_len
            0x24,
            0x14,  # sync_word
            0x0E,  # tx_power
            0x00,
            0x01,
            0x00,  # header / crc / iq
        ],
    )
    assert r.encode() == expected
    assert SetConfigResult.decode(expected) == r


# ── TxDone ────────────────────────────────────────────────────


def test_tx_done_transmitted_airtime():
    td = TxDone(result=TxResult.TRANSMITTED, airtime_us=30_976)
    assert td.encode() == bytes([0x00, 0x00, 0x79, 0x00, 0x00])
    assert TxDone.decode(td.encode()) == td


def test_tx_done_channel_busy():
    td = TxDone(result=TxResult.CHANNEL_BUSY, airtime_us=0)
    assert TxDone.decode(td.encode()) == td


# ── RxEvent ───────────────────────────────────────────────────


def test_rx_event_c26_bytes():
    rx = RxEvent(
        rssi_dbm=-73.5,
        snr_db=9.5,
        freq_err_hz=-125,
        timestamp_us=42_000_000,
        crc_valid=True,
        packets_dropped=0,
        origin=RxOrigin.OTA,
        data=bytes([0x01, 0x02, 0x03, 0x04]),
    )
    # PROTOCOL.md §C.2.6 payload (strip frame header + CRC).
    expected = bytes(
        [
            0x21,
            0xFD,  # rssi = -735 LE
            0x5F,
            0x00,  # snr = 95 LE
            0x83,
            0xFF,
            0xFF,
            0xFF,  # freq_err = -125 LE
            0x80,
            0xDE,
            0x80,
            0x02,
            0x00,
            0x00,
            0x00,
            0x00,  # ts = 42_000_000 LE
            0x01,  # crc_valid
            0x00,
            0x00,  # packets_dropped
            0x00,  # origin OTA
            0x01,
            0x02,
            0x03,
            0x04,
        ],
    )
    assert rx.encode() == expected
    decoded = RxEvent.decode(expected)
    assert decoded.rssi_dbm == pytest.approx(-73.5)
    assert decoded.snr_db == pytest.approx(9.5)
    assert decoded.data == bytes([0x01, 0x02, 0x03, 0x04])


def test_rx_event_rejects_invalid_crc_byte():
    buf = bytearray(
        RxEvent(
            rssi_dbm=0.0,
            snr_db=0.0,
            freq_err_hz=0,
            timestamp_us=0,
            crc_valid=True,
            packets_dropped=0,
            origin=RxOrigin.OTA,
            data=b"",
        ).encode(),
    )
    buf[16] = 2
    with pytest.raises(ValueError):
        RxEvent.decode(bytes(buf))


# ── ERR payload ───────────────────────────────────────────────


def test_err_payload_roundtrip():
    wire = encode_err_payload(ErrorCode.ENOT_CONFIGURED)
    assert wire == bytes([0x03, 0x00])
    assert decode_err_payload(wire) == ErrorCode.ENOT_CONFIGURED


def test_err_payload_preserves_unknown_code():
    wire = encode_err_payload(0xABCD)
    assert decode_err_payload(wire) == 0xABCD


# ── OK payload context dispatch ───────────────────────────────


def test_parse_ok_for_ping_requires_empty():
    assert parse_ok_payload(TYPE_PING, b"") is None
    with pytest.raises(ValueError):
        parse_ok_payload(TYPE_PING, b"\x00")


def test_parse_ok_for_set_config_returns_result():
    r = SetConfigResult(
        result=SetConfigResultCode.APPLIED,
        owner=Owner.MINE,
        current=LoRaConfig.default(),
    )
    parsed = parse_ok_payload(TYPE_SET_CONFIG, r.encode())
    assert parsed == r


# ── Info ──────────────────────────────────────────────────────


def _sample_info() -> Info:
    return Info(
        proto_major=1,
        proto_minor=0,
        fw_major=0,
        fw_minor=1,
        fw_patch=0,
        radio_chip_id=RadioChipId.SX1262,
        capability_bitmap=Capability.LORA | Capability.FSK | Capability.CAD_BEFORE_TX,
        supported_sf_bitmap=0x1FE0,
        supported_bw_bitmap=0x03FF,
        max_payload_bytes=255,
        rx_queue_capacity=64,
        tx_queue_capacity=16,
        freq_min_hz=150_000_000,
        freq_max_hz=960_000_000,
        tx_power_min_dbm=-9,
        tx_power_max_dbm=22,
        mcu_uid=bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x23, 0x45, 0x67]),
        radio_uid=b"",
    )


def test_info_appendix_c22_bytes():
    info = _sample_info()
    expected = bytes(
        [
            0x01,
            0x00,
            0x00,
            0x01,
            0x00,
            0x02,
            0x00,  # chip id
            0x03,
            0x00,
            0x01,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,  # cap bitmap
            0xE0,
            0x1F,  # supported SF
            0xFF,
            0x03,  # supported BW
            0xFF,
            0x00,  # max payload 255
            0x40,
            0x00,  # rx q 64
            0x10,
            0x00,  # tx q 16
            0x80,
            0xD1,
            0xF0,
            0x08,  # freq min
            0x00,
            0x70,
            0x38,
            0x39,  # freq max
            0xF7,
            0x16,  # tx power min/max
            0x08,  # mcu_uid_len
            0xDE,
            0xAD,
            0xBE,
            0xEF,
            0x01,
            0x23,
            0x45,
            0x67,
            0x00,  # radio_uid_len
        ],
    )
    assert info.encode() == expected
    assert Info.decode(expected) == info


def test_info_tolerates_trailing_bytes():
    info = _sample_info()
    wire = info.encode() + b"\xaa" * 10
    assert Info.decode(wire) == info


def test_info_supports():
    info = _sample_info()
    assert info.supports(Capability.LORA)
    assert info.supports(Capability.LORA | Capability.FSK)
    assert not info.supports(Capability.MULTI_CLIENT)
    assert info.chip == RadioChipId.SX1262
