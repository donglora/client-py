"""DongLoRa host library — talk LoRa from Python in three lines.

Quick start::

    import donglora as dl

    d = dl.connect()                  # auto-discover, auto-configure, auto-keepalive
    d.tx(b"Hello")                    # blocks until TX_DONE
    for pkt in d.rx():                # continuous receive
        print(pkt.rssi_dbm, pkt.data)

For trivial scripts, skip the handle::

    import donglora as dl
    dl.tx(b"hi")
    for pkt in dl.rx():
        ...

Customise anything via :func:`connect` kwargs:

* ``port="/dev/ttyUSB0"`` — explicit serial device
* ``config=LoRaConfig(...)`` — override the default radio config
* ``auto_configure=False`` — skip automatic SET_CONFIG
* ``keepalive=False`` — run your own session-liveness cadence

The full DongLoRa Protocol v2 surface is available via :class:`Dongle` methods
(:meth:`Dongle.tx` / :meth:`Dongle.rx` / :meth:`Dongle.set_config` /
:meth:`Dongle.ping` / :attr:`Dongle.info`) and the underlying
:mod:`donglora.frame` / :mod:`donglora.events` / :mod:`donglora.info`
modules if you need to speak the wire directly.

See ``firmware/PROTOCOL.md`` for the wire-level specification.
"""

from __future__ import annotations

from donglora._top_level import close, recv, rx, tx
from donglora.commands import (
    TYPE_GET_INFO,
    TYPE_PING,
    TYPE_RX_START,
    TYPE_RX_STOP,
    TYPE_SET_CONFIG,
    TYPE_TX,
)
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
from donglora.dongle import Dongle
from donglora.errors import (
    BusyError,
    Cancelled,
    ChannelBusy,
    DeviceError,
    DongloraError,
    ErrorCode,
    FrameError,
    InternalError,
    LengthError,
    ModulationError,
    NotConfiguredError,
    ParamError,
    RadioError,
    TimeoutError_,
    UnknownCommandError,
)
from donglora.events import (
    Owner,
    RxEvent,
    RxOrigin,
    SetConfigResult,
    SetConfigResultCode,
    TxDone,
    TxResult,
)
from donglora.frame import MAX_OTA_PAYLOAD, MAX_PAYLOAD_FIELD, MAX_WIRE_FRAME, Frame, encode_frame
from donglora.info import MAX_MCU_UID_LEN, MAX_RADIO_UID_LEN, Capability, Info, RadioChipId
from donglora.modulation import (
    FlrcBitrate,
    FlrcBt,
    FlrcCodingRate,
    FlrcConfig,
    FlrcPreambleLen,
    FskConfig,
    LoRaBandwidth,
    LoRaCodingRate,
    LoRaConfig,
    LoRaHeaderMode,
    LrFhssBandwidth,
    LrFhssCodingRate,
    LrFhssConfig,
    LrFhssGrid,
    Modulation,
    ModulationId,
)
from donglora.transport import MuxConnection

__all__ = [
    "BRIDGE_VID_PIDS",
    "DEFAULT_TIMEOUT",
    "MAX_MCU_UID_LEN",
    "MAX_OTA_PAYLOAD",
    "MAX_PAYLOAD_FIELD",
    "MAX_RADIO_UID_LEN",
    "MAX_WIRE_FRAME",
    "TYPE_GET_INFO",
    "TYPE_PING",
    "TYPE_RX_START",
    "TYPE_RX_STOP",
    "TYPE_SET_CONFIG",
    "TYPE_TX",
    "USB_PID",
    "USB_VID",
    "USB_VID_PID",
    "BusyError",
    "Cancelled",
    "Capability",
    "ChannelBusy",
    "DeviceError",
    "Dongle",
    "DongloraError",
    "ErrorCode",
    "FlrcBitrate",
    "FlrcBt",
    "FlrcCodingRate",
    "FlrcConfig",
    "FlrcPreambleLen",
    "Frame",
    "FrameError",
    "FskConfig",
    "Info",
    "InternalError",
    "LengthError",
    "LoRaBandwidth",
    "LoRaCodingRate",
    "LoRaConfig",
    "LoRaHeaderMode",
    "LrFhssBandwidth",
    "LrFhssCodingRate",
    "LrFhssConfig",
    "LrFhssGrid",
    "Modulation",
    "ModulationError",
    "ModulationId",
    "MuxConnection",
    "NotConfiguredError",
    "Owner",
    "ParamError",
    "RadioChipId",
    "RadioError",
    "RxEvent",
    "RxOrigin",
    "SetConfigResult",
    "SetConfigResultCode",
    "TimeoutError_",
    "TxDone",
    "TxResult",
    "UnknownCommandError",
    "close",
    "connect",
    "connect_default",
    "connect_mux_auto",
    "default_socket_path",
    "encode_frame",
    "find_port",
    "mux_connect",
    "mux_tcp_connect",
    "recv",
    "rx",
    "try_connect",
    "tx",
    "wait_for_device",
]
