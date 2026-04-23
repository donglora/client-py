"""USB device discovery for DongLoRa dongles.

Mirrors the Rust client's ``discovery.rs``.  Scans ``/dev/ttyACM*`` and
``/dev/ttyUSB*`` by VID:PID, preferring native USB CDC-ACM over known
USB-UART bridge chips.
"""

from __future__ import annotations

import glob
import logging
import subprocess
import time

log = logging.getLogger("donglora")

USB_VID: int = 0x1209
USB_PID: int = 0x5741
USB_VID_PID: str = "1209:5741"

BRIDGE_VID_PIDS: set[str] = {
    "10c4:ea60",  # CP2102 (Silicon Labs)
    "1a86:55d4",  # CH9102
    "1a86:7522",  # CH340K — Elecrow ThinkNode-M2 ships with this
    "1a86:7523",  # CH340
    "0403:6001",  # FT232R (FTDI)
}
"""Known USB-UART bridge VID:PIDs found on some board revisions."""


def find_port() -> str | None:
    """Find the DongLoRa serial port by USB VID:PID.

    Checks for native USB CDC-ACM first (1209:5741), then falls back to
    known USB-UART bridge chips found on some board revisions.
    """
    bridge_match: str | None = None
    for path in sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*")):
        try:
            result = subprocess.run(
                ["udevadm", "info", "--query=property", f"--name={path}"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
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
    """Block until a DongLoRa device appears, polling every 500 ms."""
    log.info("waiting for DongLoRa...")
    while True:
        port = find_port()
        if port:
            log.info("found %s", port)
            time.sleep(0.3)
            return port
        time.sleep(0.5)
