"""Tests for donglora.client — send/recv/drain_rx/validate."""

from __future__ import annotations

import struct
from io import BytesIO
from typing import Any

from donglora.client import _rx_queue, drain_rx, recv, send, validate
from donglora.codec import cobs_encode


def _make_mock(responses: list[bytes]) -> Any:
    """Create a mock transport that returns pre-encoded COBS frames."""
    wire = b""
    for resp in responses:
        wire += cobs_encode(resp)

    class Mock:
        def __init__(self) -> None:
            self._stream = BytesIO(wire)
            self.timeout = 2.0
            self._written: list[bytes] = []

        def read(self, n: int = 1) -> bytes:
            return self._stream.read(n)

        def write(self, data: bytes) -> int:
            self._written.append(data)
            return len(data)

        def flush(self) -> None:
            pass

    return Mock()


def _pong() -> bytes:
    return bytes([0])


def _ok() -> bytes:
    return bytes([4])


def _rx_packet(payload: bytes, rssi: int = -80, snr: int = 10) -> bytes:
    return (
        bytes([2])
        + struct.pack("<h", rssi)
        + struct.pack("<h", snr)
        + struct.pack("<H", len(payload))
        + payload
    )


class TestSend:
    def setup_method(self) -> None:
        _rx_queue.clear()

    def test_basic_command(self) -> None:
        mock = _make_mock([_pong()])
        resp = send(mock, "Ping")
        assert resp["type"] == "Pong"

    def test_buffers_rx_packets(self) -> None:
        mock = _make_mock([_rx_packet(b"pkt1"), _rx_packet(b"pkt2"), _ok()])
        resp = send(mock, "StartRx")
        assert resp["type"] == "Ok"
        assert len(_rx_queue) == 2

    def test_timeout(self) -> None:
        mock = _make_mock([])
        resp = send(mock, "Ping")
        assert resp["type"] == "Timeout"


class TestRecv:
    def setup_method(self) -> None:
        _rx_queue.clear()

    def test_from_buffer(self) -> None:
        _rx_queue.append({"type": "RxPacket", "rssi": -80, "snr": 10, "payload": b"buf"})
        mock = _make_mock([])
        pkt = recv(mock)
        assert pkt is not None
        assert pkt["payload"] == b"buf"

    def test_from_wire(self) -> None:
        mock = _make_mock([_rx_packet(b"wire")])
        pkt = recv(mock)
        assert pkt is not None
        assert pkt["payload"] == b"wire"

    def test_timeout(self) -> None:
        mock = _make_mock([])
        assert recv(mock) is None


class TestDrainRx:
    def setup_method(self) -> None:
        _rx_queue.clear()

    def test_drains_buffer_and_wire(self) -> None:
        _rx_queue.append({"type": "RxPacket", "rssi": 0, "snr": 0, "payload": b"buf"})
        mock = _make_mock([_rx_packet(b"wire")])
        packets = drain_rx(mock)
        assert len(packets) == 2
        assert packets[0]["payload"] == b"buf"
        assert packets[1]["payload"] == b"wire"
        assert len(_rx_queue) == 0


class TestValidate:
    def setup_method(self) -> None:
        _rx_queue.clear()

    def test_success(self) -> None:
        mock = _make_mock([_pong()])
        validate(mock)

    def test_failure(self) -> None:
        mock = _make_mock([_ok()])
        try:
            validate(mock)
            assert False, "should have raised"  # noqa: B011
        except ConnectionError:
            pass

    def test_timeout(self) -> None:
        mock = _make_mock([])
        try:
            validate(mock)
            assert False, "should have raised"  # noqa: B011
        except ConnectionError:
            pass
