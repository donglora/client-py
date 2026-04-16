"""COBS helper tests — the thin re-export layer.

Frame-level codec tests live in ``test_frame.py``.
"""

from __future__ import annotations

from cobs import cobs

from donglora.codec import cobs_encode


class TestCobsEncode:
    def test_basic(self) -> None:
        data = b"hello"
        encoded = cobs_encode(data)
        assert encoded[-1:] == b"\x00"
        assert cobs.decode(encoded[:-1]) == data

    def test_empty(self) -> None:
        encoded = cobs_encode(b"")
        assert encoded[-1:] == b"\x00"
        assert cobs.decode(encoded[:-1]) == b""

    def test_zeros(self) -> None:
        data = b"\x00\x00\x00"
        encoded = cobs_encode(data)
        assert b"\x00" not in encoded[:-1]
        assert cobs.decode(encoded[:-1]) == data

    def test_roundtrip(self) -> None:
        for length in [0, 1, 10, 100, 254, 255, 256]:
            data = bytes(range(length % 256)) * (length // 256 + 1)
            data = data[:length]
            encoded = cobs_encode(data)
            decoded = cobs.decode(encoded[:-1])
            assert decoded == data
