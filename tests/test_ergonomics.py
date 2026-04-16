"""Sanity check that the three-line happy path works.

If these tests need anything beyond ``import donglora as dl`` + three
method calls, the client lost its reason for existing.
"""

from __future__ import annotations

import donglora as dl
from donglora.events import TYPE_RX, RxOrigin


def test_happy_path_tx_is_three_lines():
    """Three lines: get a Dongle (from the test harness), tx, done."""
    from donglora.dongle import Dongle
    from donglora.modulation import LoRaConfig
    from donglora.session import Session
    from tests.test_session import FakeTransport

    t = FakeTransport()
    try:
        session = Session(t)
        info = session.get_info()
        cfg = LoRaConfig.default()
        session.set_config(cfg)
        with Dongle(session, info, applied_config=cfg, keepalive=False) as d:
            td = d.tx(b"Hello")
            assert td.result.name == "TRANSMITTED"
    finally:
        t.close()


def test_rx_iterator_yields_incoming_packets():
    """The `.rx()` iterator terminates cleanly on timeout."""
    from donglora.dongle import Dongle
    from donglora.events import RxEvent
    from donglora.modulation import LoRaConfig
    from donglora.session import Session
    from tests.test_session import FakeTransport

    t = FakeTransport()
    try:
        session = Session(t)
        info = session.get_info()
        cfg = LoRaConfig.default()
        session.set_config(cfg)
        rx = RxEvent(
            rssi_dbm=-72.0,
            snr_db=8.0,
            freq_err_hz=0,
            timestamp_us=100,
            crc_valid=True,
            packets_dropped=0,
            origin=RxOrigin.OTA,
            data=b"ping",
        )
        with Dongle(session, info, applied_config=cfg, keepalive=False) as d:
            # Inject two RX events, then time out.
            t.push_async(TYPE_RX, 0, rx.encode())
            t.push_async(TYPE_RX, 0, rx.encode())
            received: list[bytes] = []
            for pkt in d.rx(timeout=0.5):
                received.append(pkt.data)
                if len(received) == 2:
                    break
            assert received == [b"ping", b"ping"]
    finally:
        t.close()


def test_public_api_names_are_stable():
    # The top-level module exposes the core happy-path surface. If any
    # of these disappear it's a breaking change we should notice.
    for name in ("connect", "Dongle", "LoRaConfig", "tx", "rx", "recv"):
        assert hasattr(dl, name), f"donglora.{name} must stay exported"
