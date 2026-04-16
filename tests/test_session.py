"""Session-level tests: tag correlation, async events, auto-recovery.

Uses a `FakeTransport` — a thread-safe in-memory duplex pipe with a
simple script of pre-canned firmware responses. Every test exercises
the real frame codec; only the transport is faked.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from donglora.commands import (
    TYPE_GET_INFO,
    TYPE_PING,
    TYPE_RX_START,
    TYPE_SET_CONFIG,
    TYPE_TX,
)
from donglora.errors import (
    BusyError,
    Cancelled,
    ChannelBusy,
    NotConfiguredError,
)
from donglora.events import (
    TYPE_ERR,
    TYPE_OK,
    TYPE_RX,
    TYPE_TX_DONE,
    Owner,
    RxEvent,
    RxOrigin,
    SetConfigResult,
    SetConfigResultCode,
    TxDone,
    TxResult,
)
from donglora.frame import decode_frame, encode_frame
from donglora.info import Info, RadioChipId
from donglora.modulation import LoRaConfig
from donglora.session import Session

# ── A tiny in-memory transport that simulates a device ─────────


class FakeTransport:
    """Thread-safe in-memory duplex pipe with a scripted device."""

    def __init__(self, *, script: Callable[[int, int, bytes], list[bytes]] | None = None):
        self._read_buf = bytearray()
        self._read_cond = threading.Condition()
        self._write_buf = bytearray()
        self._write_cond = threading.Condition()
        self._closed = False
        self._script = script or _default_script
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="fake-transport-writer",
            daemon=True,
        )
        self._writer_thread.start()
        self.log: list[bytes] = []

    def write(self, data: bytes) -> int:
        with self._write_cond:
            self._write_buf.extend(data)
            self._write_cond.notify_all()
        return len(data)

    def flush(self) -> None:
        pass

    def read(self, n: int = 1) -> bytes:
        with self._read_cond:
            while not self._read_buf and not self._closed:
                self._read_cond.wait(timeout=0.1)
                if self._closed:
                    return b""
            chunk = bytes(self._read_buf[:n])
            del self._read_buf[:n]
            return chunk

    def close(self) -> None:
        with self._read_cond:
            self._closed = True
            self._read_cond.notify_all()
        with self._write_cond:
            self._write_cond.notify_all()

    def _writer_loop(self) -> None:
        """Read framed commands off _write_buf, feed to the script,
        push responses onto _read_buf.
        """
        while not self._closed:
            with self._write_cond:
                while not self._write_buf and not self._closed:
                    self._write_cond.wait(timeout=0.1)
                if self._closed:
                    return
                # Collect complete frames (ending in 0x00) from write_buf.
                frames_raw: list[bytes] = []
                while True:
                    try:
                        idx = self._write_buf.index(0)
                    except ValueError:
                        break
                    frames_raw.append(bytes(self._write_buf[:idx]))
                    del self._write_buf[: idx + 1]
            for raw in frames_raw:
                try:
                    frame = decode_frame(raw)
                except Exception:
                    continue
                self.log.append(raw)
                responses = self._script(frame.type_id, frame.tag, frame.payload)
                if responses:
                    with self._read_cond:
                        for r in responses:
                            self._read_buf.extend(r)
                        self._read_cond.notify_all()

    # Kick an async event (e.g. RX) into the read stream.
    def push_async(self, type_id: int, tag: int, payload: bytes) -> None:
        wire = encode_frame(type_id, tag, payload)
        with self._read_cond:
            self._read_buf.extend(wire)
            self._read_cond.notify_all()


def _default_script(type_id: int, tag: int, payload: bytes) -> list[bytes]:  # noqa: ARG001
    """Reasonable default: ACK every command with a shaped OK."""
    if type_id == TYPE_PING:
        return [encode_frame(TYPE_OK, tag, b"")]
    if type_id == TYPE_GET_INFO:
        info = _make_info()
        return [encode_frame(TYPE_OK, tag, info.encode())]
    if type_id == TYPE_SET_CONFIG:
        result = SetConfigResult(
            result=SetConfigResultCode.APPLIED,
            owner=Owner.MINE,
            current=LoRaConfig.default(),
        )
        return [encode_frame(TYPE_OK, tag, result.encode())]
    if type_id == TYPE_RX_START:
        return [encode_frame(TYPE_OK, tag, b"")]
    if type_id == TYPE_TX:
        td = TxDone(result=TxResult.TRANSMITTED, airtime_us=30_976)
        return [
            encode_frame(TYPE_OK, tag, b""),
            encode_frame(TYPE_TX_DONE, tag, td.encode()),
        ]
    return [encode_frame(TYPE_OK, tag, b"")]


def _make_info() -> Info:
    return Info(
        proto_major=1,
        proto_minor=0,
        fw_major=0,
        fw_minor=1,
        fw_patch=0,
        radio_chip_id=RadioChipId.SX1262,
        capability_bitmap=1 | (1 << 16),  # LoRa + CAD_BEFORE_TX
        supported_sf_bitmap=0x1FE0,
        supported_bw_bitmap=0x03FF,
        max_payload_bytes=255,
        rx_queue_capacity=32,
        tx_queue_capacity=1,
        freq_min_hz=150_000_000,
        freq_max_hz=960_000_000,
        tx_power_min_dbm=-9,
        tx_power_max_dbm=22,
        mcu_uid=b"\xde\xad\xbe\xef\x01\x23",
        radio_uid=b"",
    )


# ── Session tests ──────────────────────────────────────────────


@pytest.fixture
def transport():
    t = FakeTransport()
    yield t
    t.close()


def test_session_ping(transport):
    s = Session(transport)
    try:
        s.ping(timeout=2.0)
    finally:
        s.close()


def test_session_get_info_returns_info_struct(transport):
    s = Session(transport)
    try:
        info = s.get_info(timeout=2.0)
        assert isinstance(info, Info)
        assert info.proto_major == 1
    finally:
        s.close()


def test_session_set_config_returns_set_config_result(transport):
    s = Session(transport)
    try:
        result = s.set_config(LoRaConfig.default())
        assert isinstance(result, SetConfigResult)
        assert result.result == SetConfigResultCode.APPLIED
    finally:
        s.close()


def test_session_transmit_returns_tx_done(transport):
    s = Session(transport)
    try:
        td = s.transmit(b"Hello")
        assert td.result == TxResult.TRANSMITTED
        assert td.airtime_us == 30_976
    finally:
        s.close()


def test_session_transmit_channel_busy(transport):
    def script(type_id: int, tag: int, payload: bytes) -> list[bytes]:
        if type_id == TYPE_TX:
            td = TxDone(result=TxResult.CHANNEL_BUSY, airtime_us=0)
            return [
                encode_frame(TYPE_OK, tag, b""),
                encode_frame(TYPE_TX_DONE, tag, td.encode()),
            ]
        return _default_script(type_id, tag, payload)

    transport._script = script
    s = Session(transport)
    try:
        with pytest.raises(ChannelBusy):
            s.transmit(b"x")
    finally:
        s.close()


def test_session_transmit_cancelled(transport):
    def script(type_id: int, tag: int, payload: bytes) -> list[bytes]:
        if type_id == TYPE_TX:
            td = TxDone(result=TxResult.CANCELLED, airtime_us=0)
            return [
                encode_frame(TYPE_OK, tag, b""),
                encode_frame(TYPE_TX_DONE, tag, td.encode()),
            ]
        return _default_script(type_id, tag, payload)

    transport._script = script
    s = Session(transport)
    try:
        with pytest.raises(Cancelled):
            s.transmit(b"x")
    finally:
        s.close()


def test_session_err_not_configured_raises(transport):
    def script(type_id: int, tag: int, payload: bytes) -> list[bytes]:
        if type_id == TYPE_TX:
            return [encode_frame(TYPE_ERR, tag, b"\x03\x00")]
        return _default_script(type_id, tag, payload)

    transport._script = script
    s = Session(transport)
    try:
        with pytest.raises(NotConfiguredError):
            s.transmit(b"x")
    finally:
        s.close()


def test_session_err_ebusy_raises(transport):
    def script(type_id: int, tag: int, payload: bytes) -> list[bytes]:
        if type_id == TYPE_TX:
            return [encode_frame(TYPE_ERR, tag, b"\x06\x00")]
        return _default_script(type_id, tag, payload)

    transport._script = script
    s = Session(transport)
    try:
        with pytest.raises(BusyError):
            s.transmit(b"x")
    finally:
        s.close()


def test_session_async_rx_event_arrives_on_queue(transport):
    s = Session(transport)
    try:
        rx = RxEvent(
            rssi_dbm=-73.5,
            snr_db=9.5,
            freq_err_hz=0,
            timestamp_us=100,
            crc_valid=True,
            packets_dropped=0,
            origin=RxOrigin.OTA,
            data=b"\x01\x02\x03",
        )
        transport.push_async(TYPE_RX, 0, rx.encode())
        delivered = s.next_rx(timeout=2.0)
        assert delivered is not None
        assert delivered.data == b"\x01\x02\x03"
    finally:
        s.close()


def test_session_tag_correlation_across_concurrent_sends(transport):
    # Two threads each send a PING. Both must resolve against their own tag.
    s = Session(transport)
    try:
        errors: list[Exception] = []

        def do_ping() -> None:
            try:
                s.ping(timeout=2.0)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=do_ping) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)
        assert errors == []
    finally:
        s.close()
