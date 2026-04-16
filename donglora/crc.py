"""CRC-16/CCITT-FALSE — the wire-level integrity check used by DongLoRa Protocol v2.

Polynomial ``0x1021``, initial value ``0xFFFF``, no reflection,
XOR-out ``0x0000``. Also known as CRC-16/AUTOSAR or CRC-16/IBM-3740.

**Not** the same as CRC-16/KERMIT, CRC-16/XMODEM, or plain
"CRC-16/CCITT" — those use different initial values or reflect input.

Check value: ``crc16(b"123456789") == 0x29B1``. The module-level
assertion below fails at import if the implementation drifts.
"""

from __future__ import annotations


def crc16(data: bytes) -> int:
    """Compute CRC-16/CCITT-FALSE over *data*. Returns a u16."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# Self-check: the check value from PROTOCOL.md Appendix B.
assert crc16(b"123456789") == 0x29B1, "CRC-16/CCITT-FALSE check value drift"
