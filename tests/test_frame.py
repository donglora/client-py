"""Frame codec tests — every Appendix C hex vector pinned.

These match the Rust crate's ``tests/vectors.rs`` byte-for-byte. If the
client-py and firmware ever disagree, one of these tests fails first.
"""

import pytest

from donglora.commands import (
    TYPE_PING,
    TYPE_TX,
    encode_ping_payload,
    encode_tx_payload,
)
from donglora.events import TYPE_ERR, TYPE_OK, TYPE_TX_DONE
from donglora.frame import (
    Frame,
    FrameCobsError,
    FrameCrcError,
    FrameTooShortError,
    decode_frame,
    encode_frame,
    read_frame,
)

# ── §C.2.1 PING / OK ─────────────────────────────────────────────


def test_c21_ping_encodes_to_spec_bytes():
    wire = encode_frame(TYPE_PING, 0x0001, encode_ping_payload())
    assert wire == bytes([0x03, 0x01, 0x01, 0x03, 0x9D, 0xC8, 0x00])


def test_c21_ok_encodes_to_spec_bytes():
    wire = encode_frame(TYPE_OK, 0x0001, b"")
    assert wire == bytes([0x03, 0x80, 0x01, 0x03, 0xF7, 0xC4, 0x00])


# ── §C.2.4 TX / OK / TX_DONE ─────────────────────────────────────


def test_c24_tx_with_cad():
    wire = encode_frame(TYPE_TX, 0x0004, encode_tx_payload(b"Hello", skip_cad=False))
    assert wire == bytes(
        [0x03, 0x04, 0x04, 0x01, 0x08, 0x48, 0x65, 0x6C, 0x6C, 0x6F, 0x26, 0x40, 0x00],
    )


def test_c24_ok():
    wire = encode_frame(TYPE_OK, 0x0004, b"")
    assert wire == bytes([0x03, 0x80, 0x04, 0x03, 0x02, 0x3B, 0x00])


def test_c24_tx_done():
    # Payload = result(0=TRANSMITTED) + airtime_us(30976 LE).
    payload = bytes([0x00, 0x00, 0x79, 0x00, 0x00])
    wire = encode_frame(TYPE_TX_DONE, 0x0004, payload)
    assert wire == bytes(
        [0x03, 0xC1, 0x04, 0x01, 0x01, 0x02, 0x79, 0x01, 0x03, 0xE3, 0xFA, 0x00],
    )


# ── §C.2.5 TX skip_cad ──────────────────────────────────────────


def test_c25_tx_skip_cad():
    wire = encode_frame(TYPE_TX, 0x0005, encode_tx_payload(b"URGENT", skip_cad=True))
    assert wire == bytes(
        [0x03, 0x04, 0x05, 0x0A, 0x01, 0x55, 0x52, 0x47, 0x45, 0x4E, 0x54, 0xDB, 0x1C, 0x00],
    )


# ── §C.5.1 ENOTCONFIGURED ───────────────────────────────────────


def test_c51_err_notconfigured():
    # Payload = 0x0003 LE.
    wire = encode_frame(TYPE_ERR, 0x0028, bytes([0x03, 0x00]))
    assert wire == bytes([0x03, 0x81, 0x28, 0x02, 0x03, 0x03, 0x53, 0x7E, 0x00])


# ── §C.6.4 Async EFRAME (tag=0) ─────────────────────────────────


def test_c64_async_err_eframe():
    wire = encode_frame(TYPE_ERR, 0x0000, bytes([0x02, 0x01]))
    assert wire == bytes([0x02, 0x81, 0x01, 0x05, 0x02, 0x01, 0xCE, 0xEF, 0x00])


# ── §C.8.1 COBS edge: no zeros in body ─────────────────────────


def test_c81_no_zeros_in_body():
    # PING tag=0x0101 → tag bytes have no 0x00, body has no zeros.
    wire = encode_frame(TYPE_PING, 0x0101, b"")
    assert wire == bytes([0x06, 0x01, 0x01, 0x01, 0xBC, 0xD8, 0x00])


# ── Decode-side round-trip ──────────────────────────────────────


def test_decode_roundtrip_empty_payload():
    wire = encode_frame(TYPE_PING, 0x0042, b"")
    frame = decode_frame(wire[:-1])  # strip sentinel
    assert frame == Frame(type_id=TYPE_PING, tag=0x0042, payload=b"")


def test_decode_roundtrip_with_payload():
    payload = b"hello-world"
    wire = encode_frame(TYPE_TX, 0x0123, payload)
    frame = decode_frame(wire[:-1])
    assert frame.type_id == TYPE_TX
    assert frame.tag == 0x0123
    assert frame.payload == payload


def test_decode_rejects_crc_flip():
    wire = bytearray(encode_frame(TYPE_PING, 0x0001, b""))
    # Flip one byte of the CRC region.
    wire[-3] ^= 0x01
    with pytest.raises((FrameCrcError, FrameCobsError)):
        decode_frame(bytes(wire[:-1]))


def test_decode_rejects_too_short_frame():
    # COBS of a 4-byte body: [0x05, 0xAA, 0xBB, 0xCC, 0xDD]. Decodes to
    # 4 bytes, under the 5-byte minimum (type + tag + crc).
    wire = bytes([0x05, 0xAA, 0xBB, 0xCC, 0xDD])
    with pytest.raises(FrameTooShortError):
        decode_frame(wire)


# ── read_frame with a BytesIO-like reader ──────────────────────


class _FakeReader:
    def __init__(self, data: bytes):
        self._data = bytearray(data)

    def read(self, n: int = 1) -> bytes:
        if not self._data:
            return b""
        chunk = bytes(self._data[:n])
        del self._data[:n]
        return chunk


def test_read_frame_yields_decoded_frame():
    wire = encode_frame(TYPE_PING, 0x0001, b"")
    r = _FakeReader(wire)
    frame = read_frame(r)
    assert frame == Frame(type_id=TYPE_PING, tag=0x0001, payload=b"")


def test_read_frame_returns_none_on_timeout():
    r = _FakeReader(b"")
    assert read_frame(r) is None


def test_read_frame_handles_back_to_back_frames():
    a = encode_frame(TYPE_PING, 1, b"")
    b = encode_frame(TYPE_PING, 2, b"")
    r = _FakeReader(a + b)
    assert read_frame(r).tag == 1
    assert read_frame(r).tag == 2


# ── Oversized payloads rejected ────────────────────────────────


def test_encode_rejects_oversized_payload():
    from donglora.frame import MAX_PAYLOAD_FIELD, FrameTooLargeError

    with pytest.raises(FrameTooLargeError):
        encode_frame(0xC0, 0x0000, b"\x42" * (MAX_PAYLOAD_FIELD + 1))
