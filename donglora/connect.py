"""Connection auto-detection and mux client helpers.

Mirrors the Rust client's ``connect.rs``.  The :func:`connect` function
tries mux connections first (TCP via env var, then Unix socket), falling
back to direct USB serial.  This matches the Rust client's ``connect()``
behaviour.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from typing import Any

import serial

from donglora.client import validate
from donglora.discovery import find_port, wait_for_device
from donglora.transport import MuxConnection

log = logging.getLogger("donglora")

DEFAULT_TIMEOUT: float = 2.0
"""Default read timeout for connections (seconds)."""


def default_socket_path() -> str:
    """Resolve the mux socket path in priority order.

    1. ``$DONGLORA_MUX`` environment variable
    2. ``$XDG_RUNTIME_DIR/donglora/mux.sock``
    3. ``/tmp/donglora-mux.sock``
    """
    env = os.environ.get("DONGLORA_MUX")
    if env:
        return env
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return os.path.join(xdg, "donglora", "mux.sock")
    return "/tmp/donglora-mux.sock"


def _find_mux_socket() -> str | None:
    """Find an existing mux socket path, or ``None`` if no socket file exists."""
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
"""Set once this process connects via mux.  All future connect() calls
will only try mux, never fall through to direct serial."""


def _try_tcp_mux(addr: str, timeout: float) -> MuxConnection | None:
    """Try to connect to a TCP mux at *addr* (``[host:]port``).

    Returns ``None`` on failure instead of raising.
    """
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
        return mux_tcp_connect(host, port, timeout)
    except (ConnectionRefusedError, OSError):
        return None


# ── Public connection functions ───────────────────────────────────


def mux_connect(path: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> MuxConnection:
    """Connect to the DongLoRa mux daemon via Unix domain socket."""
    if path is None:
        path = _find_mux_socket()
    if path is None:
        raise FileNotFoundError("no mux socket found")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    conn = MuxConnection(sock, timeout)
    validate(conn)
    return conn


def mux_tcp_connect(host: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> MuxConnection:
    """Connect to the DongLoRa mux daemon via TCP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    conn = MuxConnection(sock, timeout)
    validate(conn)
    return conn


def connect(port: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
    """Auto-detect and connect to a DongLoRa device.

    Priority (first connection):

    1. ``DONGLORA_MUX_TCP`` env var -> TCP mux connection
    2. Unix socket mux (if socket file exists)
    3. Direct USB serial (auto-detect by VID:PID, blocks until device appears)

    If *port* is given, skips mux detection and connects directly.

    Once a mux connection succeeds, all future calls in this process only
    try the mux (waiting for it to reappear if necessary).  This prevents
    clients from stealing the serial port during a mux restart.
    """
    global _used_mux

    # Explicit port — go direct
    if port is not None:
        log.debug("opening serial port %s", port)
        ser = serial.Serial(port, baudrate=115200, timeout=timeout)
        ser.reset_input_buffer()
        validate(ser)
        return ser

    # Previously connected via mux — stay on mux, wait if necessary
    if _used_mux:
        mux_path = default_socket_path()
        while not os.path.exists(mux_path):
            log.info("Waiting for mux at %s ...", mux_path)
            time.sleep(0.5)
        conn = mux_connect(mux_path, timeout)
        return conn

    # Try TCP mux via environment variable
    tcp = os.environ.get("DONGLORA_MUX_TCP")
    if tcp:
        conn = _try_tcp_mux(tcp, timeout)
        if conn is not None:
            log.debug("connected to TCP mux at %s", tcp)
            _used_mux = True
            return conn

    # Try Unix socket mux — commit if socket exists (no fall-through)
    sock_path = _find_mux_socket()
    if sock_path is not None:
        log.debug("mux socket found at %s — connecting via mux only", sock_path)
        conn = mux_connect(sock_path, timeout)
        _used_mux = True
        return conn

    # No mux found on first attempt — direct USB serial
    port_path = find_port()
    if port_path is None:
        port_path = wait_for_device()
    log.debug("opening serial port %s", port_path)
    ser = serial.Serial(port_path, baudrate=115200, timeout=timeout)
    ser.reset_input_buffer()
    validate(ser)
    return ser


def connect_default() -> Any:
    """Connect with the default timeout.  Convenience wrapper for ``connect(None)``."""
    return connect(timeout=DEFAULT_TIMEOUT)


def connect_mux_auto(timeout: float = DEFAULT_TIMEOUT) -> Any:
    """Connect to a mux daemon only (TCP via env var, then Unix socket).

    Unlike :func:`connect`, this **never** falls back to direct USB serial.
    Returns an error if no mux is reachable — the caller can retry with
    backoff.

    This is the Python equivalent of the Rust client's "sticky mux" behaviour:
    once you decide to use the mux, you stay on the mux.
    """
    # Try TCP mux via environment variable
    tcp = os.environ.get("DONGLORA_MUX_TCP")
    if tcp:
        conn = _try_tcp_mux(tcp, timeout)
        if conn is not None:
            log.debug("connected to TCP mux at %s", tcp)
            return conn

    # Try Unix socket mux
    sock_path = _find_mux_socket()
    if sock_path is None:
        raise FileNotFoundError("no mux socket found")
    return mux_connect(sock_path, timeout)


def try_connect(timeout: float = DEFAULT_TIMEOUT) -> Any:
    """Like :func:`connect` but non-blocking when no USB device is present.

    Runs the same fallback chain (TCP mux, Unix socket mux, direct USB
    serial) but uses a single non-blocking scan instead of polling
    indefinitely for a USB device.  Raises if nothing is found.

    If a previous call connected via mux, only tries mux (raises if
    the mux socket is not currently available).
    """
    global _used_mux

    # Previously connected via mux — only try mux
    if _used_mux:
        return mux_connect(None, timeout)

    # Try TCP mux via environment variable
    tcp = os.environ.get("DONGLORA_MUX_TCP")
    if tcp:
        conn = _try_tcp_mux(tcp, timeout)
        if conn is not None:
            log.debug("connected to TCP mux at %s", tcp)
            _used_mux = True
            return conn

    # Try Unix socket mux — commit if socket exists
    sock_path = _find_mux_socket()
    if sock_path is not None:
        log.debug("mux socket found at %s — connecting via mux only", sock_path)
        conn = mux_connect(sock_path, timeout)
        _used_mux = True
        return conn

    # No mux found on first attempt — direct USB serial (single non-blocking scan)
    port_path = find_port()
    if port_path is None:
        raise FileNotFoundError("no DongLoRa device found (no mux, no USB device)")
    log.debug("opening serial port %s", port_path)
    ser = serial.Serial(port_path, baudrate=115200, timeout=timeout)
    ser.reset_input_buffer()
    validate(ser)
    return ser
