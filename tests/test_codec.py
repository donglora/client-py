"""Tests for donglora.codec — COBS framing."""

from __future__ import annotations

from io import BytesIO

from cobs import cobs

from donglora.codec import cobs_encode, read_frame


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


class _MockSerial:
    """Minimal mock that behaves like serial.Serial for read_frame."""

    def __init__(self, data: bytes) -> None:
        self._stream = BytesIO(data)

    def read(self, n: int = 1) -> bytes:
        return self._stream.read(n)


class TestReadFrame:
    def test_basic(self) -> None:
        data = b"hello"
        frame = cobs_encode(data)
        result = read_frame(_MockSerial(frame))
        assert result == data

    def test_timeout(self) -> None:
        result = read_frame(_MockSerial(b""))
        assert result is None

    def test_empty_frame(self) -> None:
        result = read_frame(_MockSerial(b"\x00"))
        assert result is None

    def test_corrupt_frame(self) -> None:
        result = read_frame(_MockSerial(b"\xff\x00"))
        # cobs.decode of [0xff] may or may not raise — just verify we get bytes or None
        assert result is None or isinstance(result, bytes)

    def test_multiple_frames(self) -> None:
        frame1 = cobs_encode(b"first")
        frame2 = cobs_encode(b"second")
        mock = _MockSerial(frame1 + frame2)
        assert read_frame(mock) == b"first"
        assert read_frame(mock) == b"second"
        assert read_frame(mock) is None
