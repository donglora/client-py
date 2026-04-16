"""Host-to-device command payload encoders and type constants."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from donglora.modulation import Modulation, encode_modulation

# Message type identifiers (PROTOCOL.md §4)
TYPE_PING: int = 0x01
TYPE_GET_INFO: int = 0x02
TYPE_SET_CONFIG: int = 0x03
TYPE_TX: int = 0x04
TYPE_RX_START: int = 0x05
TYPE_RX_STOP: int = 0x06


@dataclass(frozen=True)
class TxFlags:
    skip_cad: bool = False

    def as_byte(self) -> int:
        return 0b0000_0001 if self.skip_cad else 0


def encode_ping_payload() -> bytes:
    return b""


def encode_get_info_payload() -> bytes:
    return b""


def encode_set_config_payload(modulation: Modulation) -> bytes:
    return encode_modulation(modulation)


def encode_tx_payload(data: bytes, *, skip_cad: bool = False) -> bytes:
    if not data:
        raise ValueError("TX payload must be non-empty")
    return struct.pack("<B", TxFlags(skip_cad).as_byte()) + data


def encode_rx_start_payload() -> bytes:
    return b""


def encode_rx_stop_payload() -> bytes:
    return b""
