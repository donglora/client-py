"""Unit tests for the client-side config preparation done by ``connect()``.

Validates the auto_configure contract:

* ``tx_power_dbm`` clamps silently (both high and low sides).
* ``freq_hz`` / ``sf`` / ``bw`` raise :class:`ConfigNotSupported` when
  outside the device's advertised caps — silent substitution would hide
  regulatory or airtime-changing surprises from the caller.
* Non-LoRa modulations pass through untouched.
"""

from __future__ import annotations

import pytest

import donglora as dl
from donglora.connect import _prepare_config
from donglora.info import Info


def _info(
    *,
    freq_min_hz: int = 863_000_000,
    freq_max_hz: int = 928_000_000,
    supported_sf_bitmap: int = 0x1FE0,  # SF5..SF12
    supported_bw_bitmap: int = 0x03FF,  # sub-GHz BWs 0..9
    tx_power_min_dbm: int = -9,
    tx_power_max_dbm: int = 22,
) -> Info:
    """Build an Info with only the caps-related fields that matter here."""
    return Info(
        proto_major=1,
        proto_minor=0,
        fw_major=0,
        fw_minor=0,
        fw_patch=0,
        radio_chip_id=int(dl.RadioChipId.SX1262),
        capability_bitmap=dl.Capability.LORA,
        supported_sf_bitmap=supported_sf_bitmap,
        supported_bw_bitmap=supported_bw_bitmap,
        max_payload_bytes=255,
        rx_queue_capacity=32,
        tx_queue_capacity=1,
        freq_min_hz=freq_min_hz,
        freq_max_hz=freq_max_hz,
        tx_power_min_dbm=tx_power_min_dbm,
        tx_power_max_dbm=tx_power_max_dbm,
        mcu_uid=b"\x00" * 6,
        radio_uid=b"",
    )


# ── tx_power: clamp silently ──────────────────────────────────────


def test_tx_power_above_max_is_clamped_down():
    cfg = dl.LoRaConfig.default()
    cfg = dl.LoRaConfig(
        freq_hz=cfg.freq_hz,
        bw=cfg.bw,
        sf=cfg.sf,
        cr=cfg.cr,
        sync_word=cfg.sync_word,
        tx_power_dbm=30,
        preamble_len=cfg.preamble_len,
        header_mode=cfg.header_mode,
        payload_crc=cfg.payload_crc,
        iq_invert=cfg.iq_invert,
    )
    out = _prepare_config(_info(tx_power_max_dbm=20), cfg)
    assert isinstance(out, dl.LoRaConfig)
    assert out.tx_power_dbm == 20
    # Other fields unchanged.
    assert out.freq_hz == cfg.freq_hz
    assert out.sf == cfg.sf


def test_tx_power_below_min_is_clamped_up():
    cfg = dl.LoRaConfig.default()
    cfg = dl.LoRaConfig(
        freq_hz=cfg.freq_hz,
        bw=cfg.bw,
        sf=cfg.sf,
        cr=cfg.cr,
        sync_word=cfg.sync_word,
        tx_power_dbm=-30,
        preamble_len=cfg.preamble_len,
        header_mode=cfg.header_mode,
        payload_crc=cfg.payload_crc,
        iq_invert=cfg.iq_invert,
    )
    out = _prepare_config(_info(tx_power_min_dbm=2), cfg)
    assert isinstance(out, dl.LoRaConfig)
    assert out.tx_power_dbm == 2


def test_tx_power_inside_range_is_untouched():
    cfg = dl.LoRaConfig.default()
    out = _prepare_config(_info(), cfg)
    assert out is cfg  # same object, no replace() called


# ── freq_hz: reject (regulatory boundaries) ───────────────────────


def test_freq_below_min_raises():
    cfg = dl.LoRaConfig(
        freq_hz=300_000_000,
        bw=dl.LoRaBandwidth.KHZ_125,
        sf=7,
        cr=dl.LoRaCodingRate.CR_4_5,
        sync_word=0x3444,
        tx_power_dbm=14,
        preamble_len=8,
        header_mode=dl.LoRaHeaderMode.EXPLICIT,
        payload_crc=True,
        iq_invert=False,
    )
    with pytest.raises(dl.ConfigNotSupported, match="frequency"):
        _prepare_config(_info(freq_min_hz=863_000_000, freq_max_hz=928_000_000), cfg)


def test_freq_above_max_raises():
    cfg = dl.LoRaConfig(
        freq_hz=2_400_000_000,
        bw=dl.LoRaBandwidth.KHZ_125,
        sf=7,
        cr=dl.LoRaCodingRate.CR_4_5,
        sync_word=0x3444,
        tx_power_dbm=14,
        preamble_len=8,
        header_mode=dl.LoRaHeaderMode.EXPLICIT,
        payload_crc=True,
        iq_invert=False,
    )
    with pytest.raises(dl.ConfigNotSupported, match="frequency"):
        _prepare_config(_info(freq_min_hz=137_000_000, freq_max_hz=1_020_000_000), cfg)


# ── sf: reject (airtime / sensitivity change) ─────────────────────


def test_sf5_rejected_on_sx1276_bitmap():
    """SX1276 advertises SF6-SF12 (0x1FC0). SF5 must not silently upgrade."""
    cfg = dl.LoRaConfig(
        freq_hz=915_000_000,
        bw=dl.LoRaBandwidth.KHZ_125,
        sf=5,
        cr=dl.LoRaCodingRate.CR_4_5,
        sync_word=0x3444,
        tx_power_dbm=14,
        preamble_len=8,
        header_mode=dl.LoRaHeaderMode.EXPLICIT,
        payload_crc=True,
        iq_invert=False,
    )
    with pytest.raises(dl.ConfigNotSupported, match="SF5"):
        _prepare_config(_info(supported_sf_bitmap=0x1FC0), cfg)


# ── bw: reject (airtime change) ────────────────────────────────────


def test_bw_not_in_bitmap_raises():
    """SX128x-only 200 kHz BW on a sub-GHz-only device must be rejected."""
    cfg = dl.LoRaConfig(
        freq_hz=915_000_000,
        bw=dl.LoRaBandwidth.KHZ_200,  # bit 10 — SX128x only
        sf=7,
        cr=dl.LoRaCodingRate.CR_4_5,
        sync_word=0x3444,
        tx_power_dbm=14,
        preamble_len=8,
        header_mode=dl.LoRaHeaderMode.EXPLICIT,
        payload_crc=True,
        iq_invert=False,
    )
    with pytest.raises(dl.ConfigNotSupported, match="bandwidth"):
        _prepare_config(_info(supported_bw_bitmap=0x03FF), cfg)


# ── Non-LoRa: pass through ─────────────────────────────────────────


def test_non_lora_modulation_passes_through():
    # Frequency deliberately outside the info's range; _prepare_config
    # must not inspect it for non-LoRa modulations (firmware rejects
    # unsupported modulation IDs with EMODULATION on its own).
    fsk = dl.FskConfig(
        freq_hz=50_000_000,
        bitrate_bps=50_000,
        freq_dev_hz=25_000,
        rx_bw=0,
    )
    out = _prepare_config(_info(), fsk)
    assert out is fsk
