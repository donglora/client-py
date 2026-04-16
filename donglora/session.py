"""Internal session plumbing: tag counter, outstanding-tag correlation,
background reader thread, async event queue.

Not exposed to end users — :class:`donglora.dongle.Dongle` owns a
Session and handles all request/response traffic through it.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any

from donglora.commands import (
    TYPE_PING,
    encode_get_info_payload,
    encode_ping_payload,
    encode_rx_start_payload,
    encode_rx_stop_payload,
    encode_set_config_payload,
    encode_tx_payload,
)
from donglora.errors import (
    DongloraError,
    ErrorCode,
    FrameError,
    TimeoutError_,
    device_error,
)
from donglora.events import (
    TYPE_ERR,
    TYPE_OK,
    TYPE_RX,
    TYPE_TX_DONE,
    RxEvent,
    TxDone,
    decode_err_payload,
    parse_ok_payload,
)
from donglora.frame import (
    Frame,
    encode_frame,
    read_frame,
)
from donglora.frame import (
    FrameError as FrameCodecError,
)
from donglora.modulation import Modulation

log = logging.getLogger("donglora.session")


# Sentinel placed on ``_rx_queue`` when the reader thread exits, so any
# blocked ``next_rx`` caller unblocks promptly instead of waiting out
# its full timeout. The sentinel is filtered out before reaching user
# code.
_DEAD_SENTINEL: object = object()


# ── Pending-command tracking ───────────────────────────────────────


@dataclass
class _Pending:
    """One outstanding command awaiting a response."""

    tag: int
    cmd_type: int
    event: threading.Event
    # Result slots (one of these is filled by the reader thread):
    ok_payload: Any = None  # parsed OK payload (None for empty OKs)
    err: DongloraError | None = None
    tx_done: TxDone | None = None  # only for TX
    # TX commands get two responses: OK (enqueued) then TX_DONE. The
    # event is signalled after TX_DONE for TX; after OK/ERR for others.


class Session:
    """Owns the transport, demultiplexes inbound frames, correlates tags
    to pending commands, queues async events.

    Public API is thread-safe.
    """

    def __init__(self, transport: Any):
        self._transport = transport
        self._transport_lock = threading.Lock()

        # Tag generator: monotonic u16, skips 0.
        self._next_tag = 1
        self._tag_lock = threading.Lock()

        # Outstanding commands by tag.
        self._pending: dict[int, _Pending] = {}
        self._pending_lock = threading.Lock()

        # Async RX events + async ERR frames. The queue may also hold
        # `_DEAD_SENTINEL` to signal reader death without a user value.
        self._rx_queue: queue.Queue[Any] = queue.Queue()
        self._async_errors: queue.Queue[DongloraError] = queue.Queue()

        # Reader thread. `_reader_dead` fires when the reader loop
        # exits for any reason (transport closed, session closed,
        # unexpected exception). The Dongle watches this to drive
        # transparent reconnect.
        self._closed = threading.Event()
        self._reader_dead = threading.Event()
        self._reader = threading.Thread(
            target=self._reader_loop,
            name="donglora-reader",
            daemon=True,
        )
        self._reader.start()

    # ── Public: send / send_tx / rx / close ──────────────────────────

    def close(self) -> None:
        self._closed.set()
        # Wake any pending commands so they don't hang forever.
        with self._pending_lock:
            for p in self._pending.values():
                p.err = DongloraError("session closed")
                p.event.set()
            self._pending.clear()
        # Close the underlying transport so the reader thread's blocking
        # read unblocks and it can exit cleanly.
        import contextlib as _contextlib

        with _contextlib.suppress(Exception):
            self._transport.close()

    @property
    def is_alive(self) -> bool:
        """True while the reader thread is running and no close was requested."""
        return not self._reader_dead.is_set() and not self._closed.is_set()

    @property
    def reader_dead_event(self) -> threading.Event:
        """Event that fires when the reader thread exits (for any reason)."""
        return self._reader_dead

    def ping(self, *, timeout: float = 2.0) -> None:
        self._send_and_wait(TYPE_PING, encode_ping_payload(), timeout=timeout)

    def get_info(self, *, timeout: float = 2.0):
        return self._send_and_wait(0x02, encode_get_info_payload(), timeout=timeout)

    def set_config(self, modulation: Modulation, *, timeout: float = 2.0):
        return self._send_and_wait(
            0x03,
            encode_set_config_payload(modulation),
            timeout=timeout,
        )

    def transmit(self, data: bytes, *, skip_cad: bool = False, timeout: float = 10.0) -> TxDone:
        return self._send_tx(data, skip_cad=skip_cad, timeout=timeout)

    def rx_start(self, *, timeout: float = 2.0) -> None:
        self._send_and_wait(0x05, encode_rx_start_payload(), timeout=timeout)

    def rx_stop(self, *, timeout: float = 2.0) -> None:
        self._send_and_wait(0x06, encode_rx_stop_payload(), timeout=timeout)

    def next_rx(self, timeout: float | None) -> RxEvent | None:
        """Pop the next RX event from the queue, or ``None`` on timeout.

        ``timeout=None`` blocks forever. Returns ``None`` if the reader
        thread has died — the caller (normally :class:`Dongle`) should
        then trigger a reconnect.
        """
        try:
            item = self._rx_queue.get(block=True, timeout=timeout)
        except queue.Empty:
            return None
        if item is _DEAD_SENTINEL:
            # Reader is gone — re-post the sentinel for any other
            # waiters and return None.
            self._rx_queue.put(_DEAD_SENTINEL)
            return None
        return item

    def drain_async_errors(self) -> list[DongloraError]:
        """Return and clear any async errors observed since the last call."""
        drained = []
        while True:
            try:
                drained.append(self._async_errors.get_nowait())
            except queue.Empty:
                break
        return drained

    # ── Internal: send machinery ─────────────────────────────────────

    def _alloc_tag(self) -> int:
        with self._tag_lock:
            tag = self._next_tag
            self._next_tag = (tag + 1) & 0xFFFF
            if self._next_tag == 0:
                self._next_tag = 1
            return tag

    def _write_frame(self, type_id: int, tag: int, payload: bytes) -> None:
        wire = encode_frame(type_id, tag, payload)
        with self._transport_lock:
            self._transport.write(wire)
            flush = getattr(self._transport, "flush", None)
            if callable(flush):
                flush()

    def _register_pending(self, tag: int, cmd_type: int) -> _Pending:
        p = _Pending(tag=tag, cmd_type=cmd_type, event=threading.Event())
        with self._pending_lock:
            self._pending[tag] = p
        return p

    def _forget_pending(self, tag: int) -> None:
        with self._pending_lock:
            self._pending.pop(tag, None)

    def _send_and_wait(self, type_id: int, payload: bytes, *, timeout: float) -> Any:
        tag = self._alloc_tag()
        pending = self._register_pending(tag, type_id)
        try:
            self._write_frame(type_id, tag, payload)
            if not pending.event.wait(timeout=timeout):
                raise TimeoutError_(f"command 0x{type_id:02X} tag={tag} timed out")
            if pending.err is not None:
                raise pending.err
            return pending.ok_payload
        finally:
            self._forget_pending(tag)

    def _send_tx(self, data: bytes, *, skip_cad: bool, timeout: float) -> TxDone:
        """TX has a two-step completion: OK (enqueued) then TX_DONE.

        We re-use the same pending slot for both: the reader flags ``err``
        (early ERR during enqueue) or ``tx_done`` (after TX_DONE arrives)
        and signals the event. We skip the intermediate OK entirely — the
        reader treats the OK as "keep waiting for TX_DONE" on this tag.
        """
        tag = self._alloc_tag()
        pending = self._register_pending(tag, 0x04)
        try:
            self._write_frame(0x04, tag, encode_tx_payload(data, skip_cad=skip_cad))
            if not pending.event.wait(timeout=timeout):
                raise TimeoutError_(f"TX tag={tag} timed out waiting for TX_DONE")
            if pending.err is not None:
                raise pending.err
            if pending.tx_done is None:
                raise DongloraError("TX completed without TX_DONE (internal error)")
            return pending.tx_done
        finally:
            self._forget_pending(tag)

    # ── Reader thread ────────────────────────────────────────────────

    def _reader_loop(self) -> None:
        try:
            while not self._closed.is_set():
                try:
                    frame = read_frame(self._transport)
                except FrameCodecError as exc:
                    # CRC/COBS/length failure on an inbound frame. Surface as
                    # an async error so the caller can see it.
                    log.debug("inbound frame error: %s", exc)
                    self._async_errors.put(FrameError(str(exc)))
                    continue
                except OSError:
                    # Transport dropped (USB unplug, socket closed, etc.).
                    if not self._closed.is_set():
                        log.debug("session reader: transport closed")
                    return
                if frame is None:
                    # Transport timeout — loop and keep reading.
                    continue
                try:
                    self._dispatch(frame)
                except Exception as exc:
                    log.exception("reader dispatch failed: %s", exc)
        finally:
            # Reader is going away — wake anyone still waiting so they
            # don't hang on .event.wait() forever, and signal the
            # Dongle so it can trigger transparent reconnect.
            with self._pending_lock:
                for p in self._pending.values():
                    if p.err is None and p.tx_done is None:
                        p.err = DongloraError("transport closed")
                    p.event.set()
                self._pending.clear()
            self._reader_dead.set()
            # Poison the RX queue with a sentinel so any blocked
            # next_rx() unblocks promptly instead of waiting for its
            # full timeout. The sentinel is filtered out in next_rx.
            self._rx_queue.put(_DEAD_SENTINEL)

    def _dispatch(self, frame: Frame) -> None:
        type_id = frame.type_id
        tag = frame.tag
        payload = frame.payload

        # Async events: tag==0 or RX (which always has tag 0).
        if tag == 0:
            if type_id == TYPE_RX:
                try:
                    rx = RxEvent.decode(payload)
                except ValueError as exc:
                    log.debug("bad RX event: %s", exc)
                    self._async_errors.put(FrameError(f"bad RX payload: {exc}"))
                    return
                self._rx_queue.put(rx)
                return
            if type_id == TYPE_ERR:
                code = decode_err_payload(payload)
                self._async_errors.put(device_error(code, tag=0))
                return
            log.debug("unknown async frame type 0x%02X", type_id)
            return

        # Tag-correlated: OK / ERR / TX_DONE / RX-with-tag (never expected).
        with self._pending_lock:
            pending = self._pending.get(tag)
        if pending is None:
            log.debug("no pending command for tag 0x%04X (type 0x%02X)", tag, type_id)
            return

        if type_id == TYPE_OK:
            try:
                ok = parse_ok_payload(pending.cmd_type, payload)
            except (ValueError, KeyError) as exc:
                pending.err = DongloraError(f"bad OK payload: {exc}")
                pending.event.set()
                return
            if pending.cmd_type == 0x04:
                # TX: OK means "enqueued" — do NOT signal yet, wait for TX_DONE.
                pending.ok_payload = ok
                return
            pending.ok_payload = ok
            pending.event.set()
            return

        if type_id == TYPE_ERR:
            code = decode_err_payload(payload)
            pending.err = device_error(code, tag=tag)
            pending.event.set()
            return

        if type_id == TYPE_TX_DONE:
            try:
                td = TxDone.decode(payload)
            except ValueError as exc:
                pending.err = DongloraError(f"bad TX_DONE payload: {exc}")
                pending.event.set()
                return
            from donglora.errors import Cancelled, ChannelBusy
            from donglora.events import TxResult

            if td.result == TxResult.CHANNEL_BUSY:
                pending.err = ChannelBusy()
            elif td.result == TxResult.CANCELLED:
                pending.err = Cancelled()
            else:
                pending.tx_done = td
            pending.event.set()
            return

        log.debug("unexpected tag-correlated type 0x%02X for tag 0x%04X", type_id, tag)


_ = ErrorCode  # re-export so users can still catch specific codes
