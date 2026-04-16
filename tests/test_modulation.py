"""Per-modulation config encode/decode tests.

The LoRa test pins the Appendix C.2.3 canonical EU868 byte sequence.
The others round-trip through encode → decode.
"""

import pytest

from donglora.modulation import (
    FlrcBitrate,
    FlrcBt,
    FlrcCodingRate,
    FlrcConfig,
    FlrcPreambleLen,
    FskConfig,
    LoRaBandwidth,
    LoRaCodingRate,
    LoRaConfig,
    LoRaHeaderMode,
    LrFhssBandwidth,
    LrFhssCodingRate,
    LrFhssConfig,
    LrFhssGrid,
    decode_modulation,
    encode_modulation,
)

# ── LoRa — spec bytes ───────────────────────────────────────────


def test_lora_default_matches_appendix_c23():
    cfg = LoRaConfig.default()
    expected = bytes(
        [
            0xA0,
            0x27,
            0xBE,
            0x33,  # freq_hz = 868_100_000
            0x07,  # sf
            0x07,  # bw = Khz125
            0x00,  # cr = 4/5
            0x08,
            0x00,  # preamble_len = 8
            0x24,
            0x14,  # sync_word = 0x1424
            0x0E,  # tx_power_dbm = 14
            0x00,  # header explicit
            0x01,  # payload_crc on
            0x00,  # iq normal
        ],
    )
    assert cfg.encode() == expected


def test_lora_roundtrip():
    cfg = LoRaConfig(
        freq_hz=915_000_000,
        sf=10,
        bw=LoRaBandwidth.KHZ_250,
        cr=LoRaCodingRate.CR_4_8,
        preamble_len=32,
        sync_word=0xABCD,
        tx_power_dbm=22,
        header_mode=LoRaHeaderMode.IMPLICIT,
        payload_crc=False,
        iq_invert=True,
    )
    assert LoRaConfig.decode(cfg.encode()) == cfg


def test_lora_decode_rejects_wrong_length():
    with pytest.raises(ValueError):
        LoRaConfig.decode(b"\x00" * 14)


def test_lora_decode_rejects_invalid_enum():
    buf = bytearray(LoRaConfig.default().encode())
    buf[5] = 99  # invalid bandwidth
    with pytest.raises(ValueError):
        LoRaConfig.decode(bytes(buf))


# ── FSK ────────────────────────────────────────────────────────


def test_fsk_roundtrip_with_sync_word():
    cfg = FskConfig(
        freq_hz=868_000_000,
        bitrate_bps=50_000,
        freq_dev_hz=25_000,
        rx_bw=0x1A,
        preamble_len=32,
        sync_word=b"\x12\x34\x56\x78",
    )
    assert FskConfig.decode(cfg.encode()) == cfg


def test_fsk_rejects_oversized_sync_word():
    cfg = FskConfig(
        freq_hz=0,
        bitrate_bps=0,
        freq_dev_hz=0,
        rx_bw=0,
        preamble_len=0,
        sync_word=b"\x00" * 9,
    )
    with pytest.raises(ValueError):
        cfg.encode()


# ── LR-FHSS ────────────────────────────────────────────────────


def test_lr_fhss_roundtrip():
    cfg = LrFhssConfig(
        freq_hz=915_000_000,
        bw=LrFhssBandwidth.KHZ_137,
        cr=LrFhssCodingRate.CR_2_3,
        grid=LrFhssGrid.KHZ_25,
        hopping=True,
        tx_power_dbm=14,
    )
    assert LrFhssConfig.decode(cfg.encode()) == cfg


def test_lr_fhss_rejects_nonzero_reserved():
    cfg = LrFhssConfig(
        freq_hz=0,
        bw=LrFhssBandwidth.KHZ_39,
        cr=LrFhssCodingRate.CR_1_3,
        grid=LrFhssGrid.KHZ_25,
        hopping=False,
        tx_power_dbm=0,
    )
    buf = bytearray(cfg.encode())
    buf[9] = 1
    with pytest.raises(ValueError):
        LrFhssConfig.decode(bytes(buf))


# ── FLRC ───────────────────────────────────────────────────────


def test_flrc_roundtrip():
    cfg = FlrcConfig(
        freq_hz=2_400_000_000,
        bitrate=FlrcBitrate.KBPS_1300,
        cr=FlrcCodingRate.CR_3_4,
        bt=FlrcBt.BT_0_5,
        preamble_len=FlrcPreambleLen.BITS_24,
        sync_word=0x12345678,
        tx_power_dbm=10,
    )
    assert FlrcConfig.decode(cfg.encode()) == cfg


# ── Sum type (modulation_id prefix) ───────────────────────────


def test_encode_modulation_prepends_lora_id():
    cfg = LoRaConfig.default()
    wire = encode_modulation(cfg)
    assert wire[0] == 0x01
    assert wire[1:] == cfg.encode()


def test_decode_modulation_rejects_unknown_id():
    with pytest.raises(ValueError):
        decode_modulation(bytes([0x99]) + b"\x00" * 15)


def test_decode_modulation_dispatches_correctly():
    for cfg in (
        LoRaConfig.default(),
        FskConfig(
            freq_hz=868_000_000,
            bitrate_bps=9_600,
            freq_dev_hz=5_000,
            rx_bw=0,
            preamble_len=16,
            sync_word=b"\x12\x34",
        ),
        LrFhssConfig(
            freq_hz=915_000_000,
            bw=LrFhssBandwidth.KHZ_137,
            cr=LrFhssCodingRate.CR_2_3,
            grid=LrFhssGrid.KHZ_25,
            hopping=True,
            tx_power_dbm=14,
        ),
        FlrcConfig(
            freq_hz=2_400_000_000,
            bitrate=FlrcBitrate.KBPS_1300,
            cr=FlrcCodingRate.CR_3_4,
            bt=FlrcBt.BT_0_5,
            preamble_len=FlrcPreambleLen.BITS_24,
            sync_word=0x12345678,
            tx_power_dbm=10,
        ),
    ):
        wire = encode_modulation(cfg)
        assert decode_modulation(wire) == cfg
