# DongLoRa Python Client

Python client library for talking to a DongLoRa device — either directly
over USB or through the [mux daemon](../../mux/).

## What's in Here

- `donglora/` — the library: device discovery, COBS framing, protocol
  encoding/decoding, mux client support
- Installable as `donglora` via pip/uv

## Usage

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

## Dependencies

- `cobs` — COBS framing
- `pyserial` — USB serial communication

Optional extras: `meshcore` (crypto), `orac` (AI bot).
