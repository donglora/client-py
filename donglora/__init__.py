"""DongLoRa host library — connect, configure, send/receive LoRa packets.

Implements the DongLoRa USB protocol (COBS-framed fixed-size LE).
See firmware/PROTOCOL.md for the full specification.

Quick start::

    import donglora as dl

    ser = dl.connect()
    dl.send(ser, "SetConfig", config=dl.DEFAULT_CONFIG)
    dl.send(ser, "StartRx")

    while True:
        pkt = dl.recv(ser)
        if pkt:
            print(pkt["rssi"], pkt["payload"].hex())
"""

from donglora.client import (
    HANDSHAKE_TIMEOUT,
    drain_rx,
    recv,
    send,
    validate,
)
from donglora.codec import cobs_encode, read_frame
from donglora.connect import (
    DEFAULT_TIMEOUT,
    connect,
    connect_default,
    connect_mux_auto,
    default_socket_path,
    mux_connect,
    mux_tcp_connect,
    try_connect,
)
from donglora.discovery import (
    BRIDGE_VID_PIDS,
    USB_PID,
    USB_VID,
    USB_VID_PID,
    find_port,
    wait_for_device,
)
from donglora.protocol import (
    CMD_TAG_GET_CONFIG,
    CMD_TAG_GET_MAC,
    CMD_TAG_PING,
    CMD_TAG_SET_CONFIG,
    CMD_TAG_START_RX,
    CMD_TAG_STOP_RX,
    CMD_TAG_TRANSMIT,
    DEFAULT_CONFIG,
    ERROR_INVALID_CONFIG,
    ERROR_NO_DISPLAY,
    ERROR_NOT_CONFIGURED,
    ERROR_RADIO_BUSY,
    ERROR_TX_TIMEOUT,
    MAX_PAYLOAD,
    PREAMBLE_DEFAULT,
    RADIO_CONFIG_SIZE,
    RESP_TAG_CONFIG,
    RESP_TAG_ERROR,
    RESP_TAG_MAC_ADDRESS,
    RESP_TAG_OK,
    RESP_TAG_PONG,
    RESP_TAG_RX_PACKET,
    RESP_TAG_TX_DONE,
    TX_POWER_MAX,
    Bandwidth,
    ErrorCode,
    RadioConfig,
    decode_config,
    decode_response,
    encode_command,
    encode_config,
)
from donglora.transport import MuxConnection

__all__ = [
    "BRIDGE_VID_PIDS",
    "CMD_TAG_GET_CONFIG",
    "CMD_TAG_GET_MAC",
    # tag constants
    "CMD_TAG_PING",
    "CMD_TAG_SET_CONFIG",
    "CMD_TAG_START_RX",
    "CMD_TAG_STOP_RX",
    "CMD_TAG_TRANSMIT",
    "DEFAULT_CONFIG",
    # connect
    "DEFAULT_TIMEOUT",
    # error constants
    "ERROR_INVALID_CONFIG",
    "ERROR_NOT_CONFIGURED",
    "ERROR_NO_DISPLAY",
    "ERROR_RADIO_BUSY",
    "ERROR_TX_TIMEOUT",
    # client
    "HANDSHAKE_TIMEOUT",
    # protocol
    "MAX_PAYLOAD",
    "PREAMBLE_DEFAULT",
    "RADIO_CONFIG_SIZE",
    "RESP_TAG_CONFIG",
    "RESP_TAG_ERROR",
    "RESP_TAG_MAC_ADDRESS",
    "RESP_TAG_OK",
    "RESP_TAG_PONG",
    "RESP_TAG_RX_PACKET",
    "RESP_TAG_TX_DONE",
    "TX_POWER_MAX",
    "USB_PID",
    # discovery
    "USB_VID",
    "USB_VID_PID",
    "Bandwidth",
    "ErrorCode",
    # transport
    "MuxConnection",
    "RadioConfig",
    # codec
    "cobs_encode",
    "connect",
    "connect_default",
    "connect_mux_auto",
    "decode_config",
    "decode_response",
    "default_socket_path",
    "drain_rx",
    "encode_command",
    "encode_config",
    "find_port",
    "mux_connect",
    "mux_tcp_connect",
    "read_frame",
    "recv",
    "send",
    "try_connect",
    "validate",
    "wait_for_device",
]
