"""The user-facing :class:`Dongle` — a connected, configured, ready-to-TX radio.

Designed for "stupidly easy" ergonomics: once you have a ``Dongle`` from
:func:`donglora.connect`, you call ``.tx(data)`` and ``.rx()`` and that's
it. The keepalive daemon, inactivity-timeout auto-recovery, tag
bookkeeping, CRC, COBS — all hidden.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator

from donglora.errors import DongloraError, NotConfiguredError
from donglora.events import RxEvent, TxDone
from donglora.info import Info
from donglora.modulation import LoRaConfig, Modulation
from donglora.session import Session

log = logging.getLogger("donglora.dongle")

# Type alias for the reopener closure. Returns (new session, info,
# applied config) — the same triple ``connect()`` produces initially.
Reopener = Callable[[], tuple[Session, Info, "Modulation | None"]]

_KEEPALIVE_INTERVAL_S: float = 0.5
"""Default keepalive cadence. Spec §3.4 sets the inactivity timer to
1000 ms — we ping at 500 ms for 2x margin. Hosts that send commands
naturally won't trigger keepalive PINGs."""


class Dongle:
    """Live DongLoRa radio session.

    Normally constructed via :func:`donglora.connect`. Users who need
    full control can pass in a prebuilt transport + :class:`Session`,
    but the happy path is:

    .. code-block:: python

        import donglora as dl
        d = dl.connect()
        d.tx(b"Hello")
        for pkt in d.rx():
            print(pkt.rssi_dbm, pkt.data)

    Thread-safe: multiple threads can call ``tx`` / ``rx`` concurrently.
    """

    def __init__(
        self,
        session: Session,
        info: Info,
        *,
        applied_config: Modulation | None,
        keepalive: bool = True,
        _reopener: Reopener | None = None,
    ):
        self._session = session
        self._info = info
        self._applied_config: Modulation | None = applied_config
        self._rx_started = False
        self._closed = False

        # Reopener closure supplied by :func:`donglora.connect`. When
        # the session's reader thread dies (e.g. mux restart, USB blip)
        # and the caller invokes any method, the Dongle transparently
        # calls this to build a fresh session. ``None`` disables
        # transparent reconnect (users who constructed a Dongle
        # manually from an existing Session keep the old behaviour).
        self._reopener: Reopener | None = _reopener
        # Serialises reconnect work across concurrent method calls, so
        # multiple threads hitting a dead session only drive one
        # reconnect attempt.
        self._recover_lock = threading.Lock()

        # Keepalive daemon: sends PING every ~500 ms unless the caller
        # issued other traffic more recently. We track "time of last
        # transmit" as a simple monotonic counter.
        self._last_write_lock = threading.Lock()
        self._last_write_time = _now()
        self._keepalive_stop = threading.Event()
        self._keepalive_thread: threading.Thread | None = None
        if keepalive:
            self._keepalive_thread = threading.Thread(
                target=self._keepalive_loop,
                name="donglora-keepalive",
                daemon=True,
            )
            self._keepalive_thread.start()

    # ── User-facing API ─────────────────────────────────────────────

    @property
    def info(self) -> Info:
        """Cached ``GET_INFO`` snapshot from connect-time."""
        return self._info

    @property
    def config(self) -> Modulation | None:
        """The most-recently-applied radio config, or ``None`` if none."""
        return self._applied_config

    def tx(self, data: bytes, *, skip_cad: bool = False, timeout: float = 10.0) -> TxDone:
        """Transmit *data*. Blocks until TX_DONE arrives.

        Raises :class:`donglora.errors.ChannelBusy` if CAD detected
        activity, :class:`donglora.errors.Cancelled` if SET_CONFIG
        cancelled a queued TX, or other :class:`DongloraError`
        subclasses for device errors.
        """
        self._check_open()
        self._mark_write()
        return self._with_recovery(
            lambda: self._session.transmit(data, skip_cad=skip_cad, timeout=timeout),
        )

    def rx(self, timeout: float | None = None) -> _RxIterator:
        """Return an iterator over incoming packets.

        On first call, lazily sends ``RX_START`` to put the radio into
        continuous receive. ``timeout`` is the per-packet deadline; set
        to ``None`` to block forever (the common case for listening
        scripts).
        """
        self._check_open()
        if not self._rx_started:
            self._mark_write()
            self._with_recovery(lambda: self._session.rx_start())
            self._rx_started = True
        return _RxIterator(self, timeout)

    def recv(self, timeout: float | None = None) -> RxEvent | None:
        """Block on a single RX event. Convenience for ``next(iter(d.rx(timeout)))``.

        Returns ``None`` on timeout. Lazily starts continuous RX on
        first call. If the session dies (mux restart, transport blip)
        while waiting, transparently reconnects and returns ``None`` —
        the caller just loops and calls ``recv()`` again.
        """
        self._check_open()
        self._ensure_session_alive()
        if not self._rx_started:
            self._mark_write()
            self._with_recovery(lambda: self._session.rx_start())
            self._rx_started = True
        pkt = self._session.next_rx(timeout)
        if pkt is None and not self._session.is_alive:
            # Session died during the wait (reader posted the dead
            # sentinel which next_rx filtered to None). Reconnect now
            # so the *next* recv() sees a live session.
            self._ensure_session_alive()
        return pkt

    def rx_stop(self) -> None:
        """Stop continuous RX. Rare; most programs just close the dongle."""
        self._check_open()
        self._ensure_session_alive()
        self._mark_write()
        self._session.rx_stop()
        self._rx_started = False

    def set_config(self, config: Modulation) -> None:
        """Apply a new radio configuration. Blocks on the ``OK`` response."""
        self._check_open()
        self._ensure_session_alive()
        self._mark_write()
        self._session.set_config(config)
        self._applied_config = config
        # SET_CONFIG aborts any continuous RX on the device side.
        self._rx_started = False

    def ping(self) -> None:
        """Send a PING. Rarely needed directly — the keepalive daemon
        handles session-liveness automatically.
        """
        self._check_open()
        self._ensure_session_alive()
        self._mark_write()
        self._session.ping()

    def close(self) -> None:
        """Close the session. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._keepalive_stop.set()
        self._session.close()

    # Context manager
    def __enter__(self) -> Dongle:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── Internals ───────────────────────────────────────────────────

    def _check_open(self) -> None:
        if self._closed:
            raise DongloraError("dongle is closed")

    def _mark_write(self) -> None:
        with self._last_write_lock:
            self._last_write_time = _now()

    def _ensure_session_alive(self) -> None:
        """If the session's reader thread has died, rebuild the session.

        Blocks until reconnect succeeds or the Dongle is closed.
        No-op when the session is healthy. Safe to call concurrently —
        only one thread drives the actual reconnect, the rest wait on
        the shared lock.
        """
        if self._session.is_alive:
            return
        if self._reopener is None:
            # Manually-constructed Dongle without a reopener — surface
            # the death as an error rather than silently swallowing it.
            raise DongloraError("session closed; no reopener configured")
        with self._recover_lock:
            # Another thread may have already reconnected by the time
            # we got the lock.
            if self._session.is_alive:
                return
            self._recover_session_locked()

    def _recover_session_locked(self) -> None:
        """Replace ``self._session`` with a fresh one.

        Called under ``_recover_lock``. Retries the reopener with a
        backoff until success or the Dongle is closed. Re-applies the
        cached config (if any) and restarts RX (if it was running)
        before returning, so the caller's next command sees a live
        dongle in the same logical state.
        """
        assert self._reopener is not None
        log.warning("dongle: session died, reconnecting transparently")
        old_session = self._session
        import contextlib as _contextlib

        with _contextlib.suppress(Exception):
            old_session.close()

        backoff = 0.5
        max_backoff = 2.0
        while not self._closed and not self._keepalive_stop.is_set():
            try:
                new_session, new_info, applied = self._reopener()
            except (DongloraError, OSError) as exc:
                log.info("dongle: reconnect attempt failed (%s); retrying...", exc)
                if self._keepalive_stop.wait(backoff):
                    return  # close() fired during backoff
                backoff = min(backoff * 1.5, max_backoff)
                continue

            self._session = new_session
            self._info = new_info
            if applied is not None:
                self._applied_config = applied
            # Restart RX if the caller had it running.
            if self._rx_started:
                try:
                    new_session.rx_start()
                except DongloraError as exc:
                    log.info("dongle: restart rx after reconnect failed: %s", exc)
                    self._rx_started = False
            log.info("dongle: reconnect successful")
            return

    def _with_recovery(self, op):
        """Run *op*, transparently recovering from two kinds of drop:

        * Session reader death (mux restart, transport blip) —
          rebuild the session via :meth:`_ensure_session_alive` and
          retry once.
        * ``ERR(ENOTCONFIGURED)`` from an inactivity timeout —
          re-apply the cached config and retry once.

        Other errors pass through untouched.
        """
        self._ensure_session_alive()
        try:
            return op()
        except NotConfiguredError:
            if self._applied_config is None:
                raise
            log.info("dongle: auto-recovering after inactivity timeout")
            self._session.set_config(self._applied_config)
            return op()
        except DongloraError:
            # If the session died mid-call, reconnect and retry once.
            if not self._session.is_alive and self._reopener is not None:
                self._ensure_session_alive()
                return op()
            raise

    def _keepalive_loop(self) -> None:
        while not self._keepalive_stop.wait(_KEEPALIVE_INTERVAL_S):
            # If the session died, let the keepalive thread drive the
            # reconnect proactively — without this, we'd only notice
            # when the caller next invoked a public method.
            if not self._session.is_alive and self._reopener is not None:
                try:
                    self._ensure_session_alive()
                except DongloraError as exc:
                    log.debug("keepalive reconnect failed: %s", exc)
                continue
            with self._last_write_lock:
                since = _now() - self._last_write_time
            if since < _KEEPALIVE_INTERVAL_S:
                continue
            try:
                self._session.ping(timeout=2.0)
                with self._last_write_lock:
                    self._last_write_time = _now()
            except NotConfiguredError:
                # Session timed out during quiet period. Try to re-apply
                # the cached config so the next user call sees a live
                # session. If the caller issues a command first, the
                # with_recovery path will handle it instead — so treat
                # failures here as best-effort.
                if self._applied_config is not None:
                    try:
                        self._session.set_config(self._applied_config)
                    except Exception as exc:
                        log.debug("keepalive recovery failed: %s", exc)
            except DongloraError as exc:
                log.debug("keepalive ping failed: %s", exc)
            except Exception as exc:
                log.debug("keepalive thread quiet error: %s", exc)


class _RxIterator:
    """Iterator view over a Dongle's incoming RX events."""

    def __init__(self, dongle: Dongle, timeout: float | None):
        self._dongle = dongle
        self._timeout = timeout

    def __iter__(self) -> Iterator[RxEvent]:
        return self

    def __next__(self) -> RxEvent:
        pkt = self._dongle._session.next_rx(self._timeout)
        if pkt is None:
            raise StopIteration
        return pkt


def _now() -> float:
    import time

    return time.monotonic()


# Re-export the default LoRa config builder so users don't have to
# import from modulation.py.
__all__ = ["Dongle", "LoRaConfig"]
