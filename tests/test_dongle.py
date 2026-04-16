"""Dongle-level tests: keepalive thread, auto-recovery, context manager."""

from __future__ import annotations

import time

import pytest

from donglora.commands import TYPE_PING, TYPE_TX
from donglora.dongle import Dongle
from donglora.errors import DongloraError
from donglora.events import (
    TYPE_ERR,
    TxResult,
)
from donglora.frame import encode_frame
from donglora.modulation import LoRaConfig
from donglora.session import Session
from tests.test_session import FakeTransport, _default_script


def _make_dongle(transport: FakeTransport) -> Dongle:
    session = Session(transport)
    info = session.get_info()
    cfg = LoRaConfig.default()
    session.set_config(cfg)
    return Dongle(session, info, applied_config=cfg, keepalive=False)


def test_dongle_tx_returns_tx_done():
    t = FakeTransport()
    try:
        d = _make_dongle(t)
        with d:
            td = d.tx(b"hello")
            assert td.airtime_us == 30_976
    finally:
        t.close()


def test_dongle_info_property_exposes_cached_info():
    t = FakeTransport()
    try:
        with _make_dongle(t) as d:
            assert d.info.proto_major == 1
    finally:
        t.close()


def test_dongle_auto_recovers_from_not_configured():
    """First TX returns ENOTCONFIGURED; Dongle re-applies cached config,
    then retries and succeeds.
    """

    class FlipScript:
        def __init__(self):
            self._first_tx = True

        def __call__(self, type_id, tag, payload):
            if type_id == TYPE_TX and self._first_tx:
                self._first_tx = False
                return [encode_frame(TYPE_ERR, tag, b"\x03\x00")]  # ENOTCONFIGURED
            return _default_script(type_id, tag, payload)

    t = FakeTransport(script=FlipScript())
    try:
        with _make_dongle(t) as d:
            td = d.tx(b"retry-me")
            assert td.result == TxResult.TRANSMITTED
    finally:
        t.close()


def test_dongle_context_manager_closes_session():
    t = FakeTransport()
    try:
        d = _make_dongle(t)
        with d:
            pass
        # After exit, further operations raise DongloraError.
        with pytest.raises(DongloraError):
            d.tx(b"too-late")
    finally:
        t.close()


def test_dongle_close_is_idempotent():
    t = FakeTransport()
    try:
        d = _make_dongle(t)
        d.close()
        d.close()  # must not raise
    finally:
        t.close()


def test_dongle_keepalive_daemon_sends_pings():
    """With keepalive enabled, a quiet dongle emits PINGs at ~500ms cadence."""
    t = FakeTransport()
    try:
        session = Session(t)
        info = session.get_info()
        cfg = LoRaConfig.default()
        session.set_config(cfg)
        # Record frames sent after setup. keepalive=True starts the
        # background thread.
        t.log.clear()
        d = Dongle(session, info, applied_config=cfg, keepalive=True)
        time.sleep(0.8)  # allow at least one keepalive interval
        d.close()
        # Expect at least one PING in the log.
        from donglora.frame import decode_frame

        ping_count = sum(1 for raw in t.log if decode_frame(raw).type_id == TYPE_PING)
        assert ping_count >= 1
    finally:
        t.close()


def test_dongle_config_property_tracks_set_config():
    t = FakeTransport()
    try:
        with _make_dongle(t) as d:
            assert d.config == LoRaConfig.default()
            custom = LoRaConfig(
                freq_hz=915_000_000,
                sf=10,
                bw=d.config.bw,
                cr=d.config.cr,
            )
            d.set_config(custom)
            assert d.config == custom
    finally:
        t.close()


class _EOFTransport(FakeTransport):
    """Like FakeTransport, but `read()` raises ConnectionError after close.

    Matches the real-world ``MuxConnection.read`` / ``serial.Serial.read``
    behaviour when the remote hangs up, which is what the Dongle's
    transparent-reconnect path needs to see.
    """

    def read(self, n: int = 1) -> bytes:
        data = super().read(n)
        if not data and self._closed:
            raise ConnectionError("transport closed")
        return data


def test_dongle_transparent_reconnect_on_session_death():
    """When the session's reader dies (mux restart / transport blip),
    the Dongle transparently reopens and a subsequent ``tx()`` call
    just works. The caller never sees an exception.

    Drives it with a reopener that returns a *fresh* transport for the
    second connect — simulating the mux coming back up under a new
    process with the original radio state intact.
    """
    # Transport #1 — will be "killed" mid-test to simulate mux death.
    t1 = _EOFTransport()
    # Transport #2 — stands in for the replacement mux coming back.
    t2 = FakeTransport()

    session1 = Session(t1)
    info1 = session1.get_info()
    cfg = LoRaConfig.default()
    session1.set_config(cfg)

    def reopener():
        s = Session(t2)
        i = s.get_info()
        s.set_config(cfg)
        return (s, i, cfg)

    d = Dongle(
        session1,
        info1,
        applied_config=cfg,
        keepalive=False,
        _reopener=reopener,
    )
    try:
        # Sanity: first TX works through session #1.
        assert d.tx(b"hi").result == TxResult.TRANSMITTED

        # Simulate mux going away. Reader thread sees ConnectionError
        # on its next read and exits.
        t1.close()
        # Give the reader a moment to notice.
        time.sleep(0.2)

        # Second TX MUST succeed — Dongle reconnects through the
        # reopener transparently.
        assert d.tx(b"after-reconnect").result == TxResult.TRANSMITTED
        # And the cached config is preserved across reconnect.
        assert d.config == cfg
    finally:
        d.close()
        t2.close()


def test_dongle_without_reopener_surfaces_dead_session():
    """Manually-constructed Dongles (no reopener) must not swallow
    session death — the caller gets a real error."""
    t = _EOFTransport()
    try:
        session = Session(t)
        info = session.get_info()
        cfg = LoRaConfig.default()
        session.set_config(cfg)
        d = Dongle(session, info, applied_config=cfg, keepalive=False)  # no reopener
        t.close()
        time.sleep(0.2)  # let the reader die
        with pytest.raises(DongloraError):
            d.tx(b"no-reopener")
    finally:
        t.close()
