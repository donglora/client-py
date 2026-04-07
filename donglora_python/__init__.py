"""DongLoRa host library — connect, configure, send/receive LoRa packets.

Implements the DongLoRa USB protocol (COBS-framed fixed-size LE).
See firmware/PROTOCOL.md for the full specification.
"""

import collections
import glob
import os
import socket
import struct
import subprocess

import serial
import time
from cobs import cobs

# ── USB device discovery ──────────────────────────────────────────

USB_VID_PID = "1209:5741"

# Known USB-UART bridge VID:PIDs found on some board revisions.
BRIDGE_VID_PIDS = {"10c4:ea60", "1a86:55d4", "1a86:7523", "0403:6001"}


def find_port() -> str | None:
    """Find the DongLoRa serial port by USB VID:PID.

    Checks for native USB CDC-ACM first (1209:5741), then falls back to
    known USB-UART bridge chips found on some board revisions.
    """
    bridge_match = None
    for path in sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*")):
        try:
            result = subprocess.run(
                ["udevadm", "info", "--query=property", f"--name={path}"],
                capture_output=True, text=True, timeout=2,
            )
            props = dict(
                line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
            )
            vid = props.get("ID_VENDOR_ID", "").lower()
            pid = props.get("ID_MODEL_ID", "").lower()
            vid_pid = f"{vid}:{pid}"
            if vid_pid == USB_VID_PID:
                return path
            if bridge_match is None and vid_pid in BRIDGE_VID_PIDS:
                bridge_match = path
        except Exception:
            continue
    if bridge_match is not None:
        return bridge_match
    ports = sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*"))
    return ports[0] if ports else None


def wait_for_device() -> str:
    """Block until a DongLoRa device appears."""
    print("Waiting for DongLoRa...", end="", flush=True)
    while True:
        port = find_port()
        if port:
            print(f" found {port}")
            time.sleep(0.3)
            return port
        print(".", end="", flush=True)
        time.sleep(0.5)


# ── COBS framing ─────────────────────────────────────────────────

def cobs_encode(data: bytes) -> bytes:
    return cobs.encode(data) + b"\x00"


def read_frame(ser: serial.Serial) -> bytes | None:
    """Read one COBS frame. Returns decoded bytes or None on timeout."""
    buf = b""
    while True:
        b = ser.read(1)
        if not b:
            return None
        if b == b"\x00":
            break
        buf += b
    if not buf:
        return None
    try:
        return cobs.decode(buf)
    except cobs.DecodeError:
        return None


# ── Fixed-size LE encoding ────────────────────────────────────────

def encode_config(cfg: dict) -> bytes:
    """Encode a RadioConfig to 13 fixed-size LE bytes."""
    return struct.pack("<IBBBHBHB",
        cfg["freq_hz"],
        cfg["bw"],
        cfg["sf"],
        cfg["cr"],
        cfg["sync_word"],
        cfg["tx_power_dbm"] & 0xFF,  # i8 as unsigned byte
        cfg.get("preamble_len", 0),  # 0 = firmware default (16)
        cfg.get("cad", 1),           # 0 = off, 1 = on (default)
    )


def encode_command(cmd: str, **kwargs) -> bytes:
    """Encode a command to fixed-size LE bytes."""
    tags = {
        "Ping": 0, "GetConfig": 1, "SetConfig": 2, "StartRx": 3,
        "StopRx": 4, "Transmit": 5, "DisplayOn": 6, "DisplayOff": 7,
        "GetMac": 8,
    }
    out = bytes([tags[cmd]])
    if cmd == "SetConfig":
        out += encode_config(kwargs["config"])
    elif cmd == "Transmit":
        config = kwargs.get("config")
        if config is None:
            out += b"\x00"
        else:
            out += b"\x01" + encode_config(config)
        payload = kwargs["payload"]
        out += struct.pack("<H", len(payload)) + payload
    return out


# ── Response decoding ────────────────────────────────────────────

def decode_response(data: bytes) -> dict:
    """Decode a fixed-size LE response."""
    if not data:
        return {"type": "Empty"}
    tag = data[0]
    rest = data[1:]
    if tag == 0:
        return {"type": "Pong"}
    elif tag == 1:
        if len(rest) >= 13:
            freq_hz, bw, sf, cr, sync_word, pwr, preamble_len, cad = struct.unpack_from("<IBBBHBHB", rest, 0)
            tx_power_dbm = struct.unpack_from("<b", rest, 9)[0]
            return {"type": "Config", "freq_hz": freq_hz, "bw": bw, "sf": sf,
                    "cr": cr, "sync_word": sync_word, "tx_power_dbm": tx_power_dbm,
                    "preamble_len": preamble_len, "cad": cad}
        return {"type": "Config", "raw": rest.hex()}
    elif tag == 2:
        rssi = struct.unpack_from("<h", rest, 0)[0]
        snr = struct.unpack_from("<h", rest, 2)[0]
        plen = struct.unpack_from("<H", rest, 4)[0]
        payload = rest[6:6 + plen]
        return {"type": "RxPacket", "rssi": rssi, "snr": snr, "payload": payload}
    elif tag == 3:
        return {"type": "TxDone"}
    elif tag == 4:
        return {"type": "Ok"}
    elif tag == 5:
        code = rest[0] if rest else -1
        return {"type": "Error", "code": code}
    elif tag == 6:
        if len(rest) >= 6:
            mac = ":".join(f"{b:02X}" for b in rest[:6])
            return {"type": "MacAddress", "mac": mac}
        return {"type": "MacAddress", "raw": rest.hex()}
    else:
        return {"type": f"Unknown({tag})"}


# ── High-level helpers ───────────────────────────────────────────

# Buffer for RxPacket frames encountered while waiting for solicited responses.
# These are real received LoRa data — don't discard them.
_rx_queue: collections.deque = collections.deque(maxlen=256)


def send(ser: serial.Serial, cmd: str, **kwargs) -> dict:
    """Send a command and return the solicited response.

    Any unsolicited RxPacket frames encountered while waiting are buffered
    in the module-level receive queue (retrievable via recv/drain_rx).
    """
    ser.write(cobs_encode(encode_command(cmd, **kwargs)))
    ser.flush()
    for _ in range(50):  # safety bound — don't loop forever
        data = read_frame(ser)
        if data is None:
            return {"type": "Timeout"}
        resp = decode_response(data)
        if resp["type"] == "RxPacket":
            _rx_queue.append(resp)
            continue
        return resp
    return {"type": "Timeout"}


def recv(ser: serial.Serial) -> dict | None:
    """Return the next RxPacket from the buffer or the wire.

    Returns None on timeout (no packet available).
    """
    if _rx_queue:
        return _rx_queue.popleft()
    data = read_frame(ser)
    if data is None:
        return None
    resp = decode_response(data)
    if resp["type"] == "RxPacket":
        return resp
    return None


def drain_rx(ser: serial.Serial) -> list[dict]:
    """Drain all buffered and pending RxPacket frames."""
    packets = list(_rx_queue)
    _rx_queue.clear()
    old_timeout = ser.timeout
    ser.timeout = 0.01
    while True:
        data = read_frame(ser)
        if data is None:
            break
        resp = decode_response(data)
        if resp["type"] == "RxPacket":
            packets.append(resp)
    ser.timeout = old_timeout
    return packets


# ── Mux client support ──────────────────────────────────────────

class MuxConnection:
    """Drop-in replacement for serial.Serial that talks to the mux daemon."""

    def __init__(self, sock: socket.socket, timeout: float = 2.0):
        self._sock = sock
        self._timeout = timeout
        self._sock.settimeout(timeout)

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = value
        self._sock.settimeout(value)

    def read(self, n: int = 1) -> bytes:
        try:
            data = self._sock.recv(n)
            if not data:
                raise ConnectionError("mux disconnected")
            return data
        except socket.timeout:
            return b""

    def write(self, data: bytes) -> int:
        self._sock.sendall(data)
        return len(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self._sock.close()


def _mux_socket_path() -> str | None:
    """Resolve the mux socket path, or None if no socket exists."""
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


def mux_connect(path: str | None = None, timeout: float = 2.0) -> MuxConnection:
    """Connect to the DongLoRa mux daemon via Unix socket."""
    if path is None:
        path = _mux_socket_path()
    if path is None:
        raise FileNotFoundError("No mux socket found")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    return MuxConnection(sock, timeout)


def mux_tcp_connect(host: str, port: int, timeout: float = 2.0) -> MuxConnection:
    """Connect to the DongLoRa mux daemon via TCP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    return MuxConnection(sock, timeout)


_mux_mode: tuple | None = None  # ("unix",) or ("tcp", host, port) once sticky


def _reconnect_mux(timeout: float) -> MuxConnection:
    """Retry the mux connection until it comes back."""
    assert _mux_mode is not None
    print("Waiting for mux...", end="", flush=True)
    while True:
        try:
            if _mux_mode[0] == "unix":
                return mux_connect(timeout=timeout)
            else:
                return mux_tcp_connect(_mux_mode[1], _mux_mode[2], timeout)
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            print(".", end="", flush=True)
            time.sleep(1)


def connect(port: str | None = None, timeout: float = 2.0) -> serial.Serial | MuxConnection:
    """Open a connection to a DongLoRa device.

    Priority: DONGLORA_MUX_TCP env var → Unix socket mux → direct USB serial.
    Once connected via mux, subsequent calls only retry mux (never steals USB).
    """
    global _mux_mode

    # Sticky mux — if we connected via mux before, only retry mux
    if _mux_mode is not None and port is None:
        return _reconnect_mux(timeout)

    if port is None:
        # Try local Unix socket mux
        sock_path = _mux_socket_path()
        if sock_path is not None:
            try:
                conn = mux_connect(sock_path, timeout=timeout)
                _mux_mode = ("unix",)
                return conn
            except (ConnectionRefusedError, OSError):
                pass  # stale socket — fall through

        # Try TCP mux (e.g. remote access over Tailscale)
        tcp = os.environ.get("DONGLORA_MUX_TCP")
        if tcp:
            try:
                host, _, p = tcp.rpartition(":")
                host = host or "localhost"
                conn = mux_tcp_connect(host, int(p), timeout)
                _mux_mode = ("tcp", host, int(p))
                return conn
            except (ConnectionRefusedError, OSError):
                pass  # mux not reachable — fall through

        # No mux available — direct USB serial
    if port is None:
        port = wait_for_device()
    ser = serial.Serial(port, baudrate=115200, timeout=timeout)
    ser.reset_input_buffer()
    return ser


# Sentinel: set TX power to the board's maximum
TX_POWER_MAX = -128  # i8::MIN on the wire

# Sentinel: use firmware default preamble length (16 symbols)
PREAMBLE_DEFAULT = 0

# Default radio config: 915 MHz, 125 kHz BW, SF7, CR 4/5, max power, default preamble
DEFAULT_CONFIG = {
    "freq_hz": 915_000_000,
    "bw": 7,        # 125 kHz
    "sf": 7,
    "cr": 5,         # CR 4/5
    "sync_word": 0x1424,
    "tx_power_dbm": TX_POWER_MAX,
    "preamble_len": PREAMBLE_DEFAULT,
}
