# DongLoRa Python Client

Python client library for talking to a DongLoRa device — either directly
over USB or through the [mux daemon](https://github.com/donglora/mux-py).

## Install

```
pip install donglora
```

Or with [uv](https://docs.astral.sh/uv/):

```
uv add donglora
```

## Quick Start

```python
import donglora as dl

ser = dl.connect()
dl.send(ser, "SetConfig", config=dl.DEFAULT_CONFIG)
dl.send(ser, "StartRx")

while True:
    pkt = dl.recv(ser)
    if pkt:
        print(pkt["rssi"], pkt["payload"].hex())
```

## Connection Functions

| Function | Description |
|----------|-------------|
| `connect()` | Auto-detect: TCP mux, Unix socket mux, then USB serial |
| `connect_default()` | Convenience wrapper with default timeout |
| `try_connect()` | Like `connect()` but non-blocking — raises if no device found |
| `connect_mux_auto()` | Mux only — never falls back to USB serial |
| `mux_connect()` | Connect via Unix domain socket |
| `mux_tcp_connect()` | Connect via TCP |

## Module Structure

| Module | Contents |
|--------|----------|
| `donglora.protocol` | Wire types, RadioConfig, encode/decode, constants |
| `donglora.codec` | COBS framing |
| `donglora.discovery` | USB device discovery by VID:PID |
| `donglora.transport` | MuxConnection (socket wrapper) |
| `donglora.connect` | Connection auto-detection and mux helpers |
| `donglora.client` | High-level send/recv/validate |

Everything is re-exported from the top-level `donglora` package.

## Dependencies

- `cobs` — COBS framing
- `pyserial` — USB serial communication

Optional extras: `meshcore` (crypto), `orac` (AI bot).

## Development

```
just check    # fmt + lint + test
just fmt      # format code
just test     # run tests
```
