"""Auto-detect and connect to a DongLoRa device.

``connect()`` is the "60-seconds-to-hacking" entry point. In its zero-argument
form it:

1. Finds a DongLoRa USB device (or mux socket if one is available).
2. Opens the transport at 115200 baud.
3. Sends ``GET_INFO`` to confirm we're talking DongLoRa Protocol v2.
4. Applies a sensible default :class:`LoRaConfig` via ``SET_CONFIG``,
   auto-clamping ``tx_power_dbm`` against the device's advertised cap
   and raising :class:`ConfigNotSupported` for out-of-range frequency,
   spreading factor, or bandwidth.
5. Spawns a keepalive thread to keep the session alive.
6. Returns a :class:`Dongle` ready for ``.tx()`` / ``.rx()``. The
   actually-applied config (post-clamp) is exposed on
   :attr:`Dongle.config`.

Every step is overrideable via keyword arguments. See ``connect``'s docstring.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import socket
import time
from typing import Any

import serial

from donglora.discovery import find_port, wait_for_device
from donglora.dongle import Dongle
from donglora.errors import ConfigNotSupported, DongloraError
from donglora.info import Info
from donglora.modulation import LoRaConfig, Modulation
from donglora.session import Session
from donglora.transport import MuxConnection

log = logging.getLogger("donglora.connect")

DEFAULT_TIMEOUT: float = 2.0
"""Default transport read timeout (seconds). This is the *poll* interval
— overall command deadlines are per-call kwargs on the Dongle API."""


def default_socket_path() -> str:
    """Resolve the mux socket path in priority order."""
    env = os.environ.get("DONGLORA_MUX")
    if env:
        return env
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return os.path.join(xdg, "donglora", "mux.sock")
    return "/tmp/donglora-mux.sock"


def _find_mux_socket() -> str | None:
    env = os.environ.get("DONGLORA_MUX")
    if env:
        return env if os.path.exists(env) else None
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        p = os.path.join(xdg, "donglora", "mux.sock")
        if os.path.exists(p):
            return p
    p = "/tmp/donglora-mux.sock"
    return p if os.path.exists(p) else None


_used_mux = False


def _try_tcp_mux(addr: str, timeout: float) -> MuxConnection | None:
    if ":" in addr:
        host, _, port_str = addr.rpartition(":")
        host = host or "localhost"
    else:
        host = "localhost"
        port_str = addr
    try:
        port = int(port_str)
    except ValueError:
        return None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        return MuxConnection(sock, timeout)
    except (ConnectionRefusedError, OSError):
        return None


def _open_transport(port: str | None, timeout: float) -> Any:
    """Bottom-level transport opener. Returns a serial/socket-like object.

    Priority: explicit port → sticky mux → TCP mux env → Unix mux socket → USB auto-detect.
    """
    global _used_mux

    if port is not None:
        log.debug("opening serial port %s", port)
        ser = serial.Serial(port, baudrate=115200, timeout=timeout)
        ser.reset_input_buffer()
        return ser

    if _used_mux:
        mux_path = default_socket_path()
        while not os.path.exists(mux_path):
            log.info("Waiting for mux at %s ...", mux_path)
            time.sleep(0.5)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(mux_path)
        return MuxConnection(sock, timeout)

    tcp = os.environ.get("DONGLORA_MUX_TCP")
    if tcp:
        conn = _try_tcp_mux(tcp, timeout)
        if conn is not None:
            log.debug("connected to TCP mux at %s", tcp)
            _used_mux = True
            return conn

    sock_path = _find_mux_socket()
    if sock_path is not None:
        log.debug("mux socket found at %s", sock_path)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(sock_path)
        _used_mux = True
        return MuxConnection(sock, timeout)

    port_path = find_port()
    if port_path is None:
        port_path = wait_for_device()
    log.debug("opening serial port %s", port_path)
    ser = serial.Serial(port_path, baudrate=115200, timeout=timeout)
    ser.reset_input_buffer()
    return ser


def _prepare_config(info: Info, config: Modulation) -> Modulation:
    """Validate and auto-adjust *config* against the device's advertised caps.

    Per-field policy:

    * ``tx_power_dbm``: clamped into ``[tx_power_min_dbm, tx_power_max_dbm]``.
      A clamp is logged at INFO — "give me max power" quietly returning less
      is the universally-expected behavior and not worth a hard error.
    * ``freq_hz``: rejected with :class:`ConfigNotSupported` when outside
      ``[freq_min_hz, freq_max_hz]``. Silently shifting a 915 MHz request
      to 868 MHz (or vice versa) would cross regulatory boundaries.
    * ``sf``, ``bw``: rejected with :class:`ConfigNotSupported` when the
      corresponding capability bit isn't set. These change airtime and
      sensitivity dramatically; silent substitution is more confusing
      than helpful.

    Non-LoRa modulations pass through untouched — the firmware rejects
    unsupported modulation IDs with ``EMODULATION`` on its own.
    """
    if not isinstance(config, LoRaConfig):
        return config

    cfg: LoRaConfig = config

    if not (info.freq_min_hz <= cfg.freq_hz <= info.freq_max_hz):
        raise ConfigNotSupported(
            f"frequency {cfg.freq_hz} Hz outside device range "
            f"[{info.freq_min_hz}, {info.freq_max_hz}] Hz"
        )

    if not (info.supported_sf_bitmap & (1 << cfg.sf)):
        supported = [i for i in range(16) if info.supported_sf_bitmap & (1 << i)]
        raise ConfigNotSupported(
            f"SF{cfg.sf} not supported by this device (supports SF{supported})"
        )

    bw_bit = int(cfg.bw)
    if not (info.supported_bw_bitmap & (1 << bw_bit)):
        raise ConfigNotSupported(
            f"bandwidth {cfg.bw.name} (bit {bw_bit}) not in "
            f"supported_bw_bitmap 0x{info.supported_bw_bitmap:04X}"
        )

    if cfg.tx_power_dbm > info.tx_power_max_dbm:
        log.info(
            "clamping tx_power_dbm: requested %d dBm, device max %d dBm",
            cfg.tx_power_dbm,
            info.tx_power_max_dbm,
        )
        cfg = dataclasses.replace(cfg, tx_power_dbm=info.tx_power_max_dbm)
    elif cfg.tx_power_dbm < info.tx_power_min_dbm:
        log.info(
            "clamping tx_power_dbm: requested %d dBm, device min %d dBm",
            cfg.tx_power_dbm,
            info.tx_power_min_dbm,
        )
        cfg = dataclasses.replace(cfg, tx_power_dbm=info.tx_power_min_dbm)

    return cfg


def connect(
    port: str | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    config: Modulation | None = None,
    auto_configure: bool = True,
    keepalive: bool = True,
) -> Dongle:
    """Connect to a DongLoRa device and return a ready-to-use :class:`Dongle`.

    The default (zero-argument) invocation:

    * Auto-discovers a USB device (or mux socket).
    * Sends ``GET_INFO`` to confirm DongLoRa Protocol v2.
    * Applies ``LoRaConfig.default()`` (EU868 / SF7 / BW125 / CR4/5).
    * Starts a background keepalive thread.

    Parameters
    ----------
    port
        Explicit serial device path. Skips auto-discovery.
    timeout
        Transport read timeout (polling interval). Default 2 s.
    config
        Modulation to apply at connect-time. Default:
        :meth:`LoRaConfig.default`. Pass ``None`` with
        ``auto_configure=False`` to skip configuration entirely.
        With ``auto_configure=True`` (default), ``tx_power_dbm`` is
        silently clamped to the device's ``tx_power_max_dbm`` /
        ``tx_power_min_dbm``; out-of-range ``freq_hz``, ``sf``, or
        ``bw`` raise :class:`ConfigNotSupported`. Inspect
        :attr:`Dongle.config` after connect to see what the device
        actually stored.
    auto_configure
        If False, skip the ``SET_CONFIG`` step entirely — no
        validation, no clamping. The caller is then responsible for
        calling :meth:`Dongle.set_config` before TX/RX.
    keepalive
        If False, skip the keepalive daemon thread. The caller is
        responsible for periodic :meth:`Dongle.ping` calls to stay
        under the 1 s inactivity timer.

    """

    def _open_and_init() -> tuple[Session, Info, Modulation | None]:
        """Open the transport, bring up a Session, and verify+configure.

        Used for both the initial connect and any later transparent
        reconnect driven by :meth:`Dongle._recover_session`. Respects
        the sticky-mux state at call time — so a mux-first first call
        followed by a reconnect will stay on mux even if USB came back.
        """
        transport = _open_transport(port, timeout)
        session = Session(transport)
        try:
            info = session.get_info(timeout=max(timeout, 2.0))
        except DongloraError:
            session.close()
            raise
        if not isinstance(info, Info):
            session.close()
            raise DongloraError(f"GET_INFO returned unexpected payload: {info!r}")
        if info.proto_major != 1:
            session.close()
            raise DongloraError(
                f"device speaks DongLoRa Protocol v{info.proto_major}.{info.proto_minor}; "
                "this client requires v1.x",
            )

        applied: Modulation | None = None
        if auto_configure:
            requested: Modulation = config if config is not None else LoRaConfig.default()
            try:
                prepared = _prepare_config(info, requested)
                result = session.set_config(prepared, timeout=max(timeout, 2.0))
            except DongloraError:
                session.close()
                raise
            # Firmware echoes back the modulation it actually stored. Trust
            # that rather than our own `prepared` — it's the same value
            # today, but stays correct if firmware ever adds its own
            # normalization.
            applied = result.current if result is not None else prepared
        return session, info, applied

    session, info, applied = _open_and_init()
    return Dongle(
        session,
        info,
        applied_config=applied,
        keepalive=keepalive,
        _reopener=_open_and_init,
    )


def connect_default() -> Dongle:
    """Convenience wrapper for ``connect()`` with all defaults."""
    return connect()


def connect_mux_auto(timeout: float = DEFAULT_TIMEOUT) -> Dongle:
    """Connect via mux only — never falls through to direct USB serial.

    Sets the sticky-mux flag on success so any later :func:`connect`
    call also stays on the mux.
    """
    global _used_mux
    tcp = os.environ.get("DONGLORA_MUX_TCP")
    if tcp:
        conn = _try_tcp_mux(tcp, timeout)
        if conn is not None:
            _used_mux = True
            return _session_on(conn)

    sock_path = _find_mux_socket()
    if sock_path is None:
        raise FileNotFoundError("no mux socket found")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(sock_path)
    _used_mux = True
    return _session_on(MuxConnection(sock, timeout))


def try_connect(timeout: float = DEFAULT_TIMEOUT) -> Dongle:
    """Like :func:`connect` but single-scan USB (no blocking wait)."""
    global _used_mux
    if _used_mux:
        return connect_mux_auto(timeout)

    tcp = os.environ.get("DONGLORA_MUX_TCP")
    if tcp:
        conn = _try_tcp_mux(tcp, timeout)
        if conn is not None:
            _used_mux = True
            return _session_on(conn)

    sock_path = _find_mux_socket()
    if sock_path is not None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(sock_path)
        _used_mux = True
        return _session_on(MuxConnection(sock, timeout))

    port_path = find_port()
    if port_path is None:
        raise FileNotFoundError("no DongLoRa device found (no mux, no USB device)")
    ser = serial.Serial(port_path, baudrate=115200, timeout=timeout)
    ser.reset_input_buffer()
    return _session_on(ser)


def mux_connect(path: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> Dongle:
    """Connect to the mux daemon via Unix domain socket.

    Sets the sticky-mux flag on success so any later :func:`connect`
    call also stays on the mux.
    """
    global _used_mux
    if path is None:
        path = _find_mux_socket()
    if path is None:
        raise FileNotFoundError("no mux socket found")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    _used_mux = True
    return _session_on(MuxConnection(sock, timeout))


def mux_tcp_connect(host: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> Dongle:
    """Connect to the mux daemon via TCP.

    Sets the sticky-mux flag on success so any later :func:`connect`
    call also stays on the mux.
    """
    global _used_mux
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    _used_mux = True
    return _session_on(MuxConnection(sock, timeout))


def _session_on(transport: Any) -> Dongle:
    """Bring up a :class:`Dongle` on an already-open transport."""
    session = Session(transport)
    try:
        info = session.get_info()
    except DongloraError:
        session.close()
        raise
    if not isinstance(info, Info):
        session.close()
        raise DongloraError(f"GET_INFO returned unexpected payload: {info!r}")
    if info.proto_major != 1:
        session.close()
        raise DongloraError(
            f"device speaks DongLoRa Protocol v{info.proto_major}.{info.proto_minor}; this client requires v1.x",
        )
    try:
        prepared = _prepare_config(info, LoRaConfig.default())
        result = session.set_config(prepared)
    except DongloraError:
        session.close()
        raise
    applied = result.current if result is not None else prepared
    return Dongle(session, info, applied_config=applied, keepalive=True)
