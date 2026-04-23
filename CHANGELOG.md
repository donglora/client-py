# Changelog

## 1.1.0 — 2026-04-23

### Added

- `connect()` now validates and auto-adjusts the requested
  `LoRaConfig` against the device's advertised caps (`GET_INFO`):
  - `tx_power_dbm` is silently clamped into
    `[tx_power_min_dbm, tx_power_max_dbm]`. A clamp is logged at
    INFO. This keeps `dl.connect(config=my_config)` "just work" on
    boards with lower PA ceilings (e.g. SX1276 @ 20 dBm vs SX1262
    @ 22 dBm) without any per-board bookkeeping by the caller.
  - `freq_hz` outside the device's range, `sf` not in
    `supported_sf_bitmap`, or `bw` not in `supported_bw_bitmap` now
    raise :class:`ConfigNotSupported` *before* `SET_CONFIG` hits
    the wire. Silent shifts here would cross regulatory boundaries
    or change airtime/sensitivity without the caller noticing.
  - `Dongle.config` is now populated from `SetConfigResult.current`
    — the modulation the device actually stored, post-clamp — so
    callers can inspect what landed.
- New `ConfigNotSupported` exception (subclass of `DongloraError`),
  exported at the package root.

## 1.0.1 — 2026-04-22

### Fixed

- `discovery.find_port` / `wait_for_device` now match the WCH CH340K
  USB-UART bridge (`1a86:7522`) in `BRIDGE_VID_PIDS`. The Elecrow
  ThinkNode-M2 board ships with a CH340K bridge; the previous set
  covered CP2102, CH9102, standard CH340, and FTDI but missed this
  specific revision, so `discovery` returned `None` on that board.

## 1.0.0 — 2026-04-22

The 1.0 Python client, mirroring the Rust client 1.0 API and the
DongLoRa Protocol v2 wire format.

### Breaking

- **DongLoRa Protocol v2 wire format** (wire-incompatible with 0.x
  firmware and clients). All message types, tag correlation, and
  framing now follow `PROTOCOL.md` v1.0.
- **Module split.** Monolithic `protocol.py` / `client.py` are replaced
  with: `dongle.py` (high-level async `Dongle`), `session.py` (reader
  task, tag routing, keepalive), `frame.py` (streaming `FrameDecoder`
  + `encode_frame`), `commands.py` / `events.py` / `errors.py` /
  `modulation.py` / `info.py` / `crc.py`, matching the
  `donglora-protocol` Rust crate module-for-module.
- **Async API throughout.** Serial I/O via `asyncio-serial`; mux
  connections via `asyncio` streams. The blocking client surface is
  gone.
- **New error hierarchy.** `DongloraError` base with `Timeout`,
  `TransportClosed`, `ReaderExited`, `BadFrame`, and `ErrClient...`
  variants mirroring the Rust client's `ClientError`.

### Added

- Tag-aware dispatch with concurrent in-flight commands. The
  `TagAllocator` hands out 16-bit device tags; `Session` routes each
  response back to the originating coroutine.
- Auto-recovery from `ERR(ENOTCONFIGURED)`. The `Dongle` caches the
  last `SET_CONFIG` and silently re-applies it on timeout, retrying
  once.
- 500 ms background keepalive task per `PROTOCOL.md §3.4`.
- Sticky mux reconnect: once a mux connection succeeds, all future
  `connect()` calls in the same process only try the mux (waiting
  for it to reappear if needed). `try_connect()` raises immediately
  so callers can retry with backoff. Prevents clients from stealing
  the serial port during mux restarts.

### Test suite

- New tests: `test_dongle`, `test_session`, `test_frame`, `test_events`,
  `test_modulation`, `test_crc`, `test_ergonomics`.
- Removed: `test_client`, `test_protocol` (superseded).

## 0.2.0 — 2026-04-08

### Features

- **Module split matching Rust structure** — split monolithic `__init__.py` into
  `protocol.py`, `codec.py`, `discovery.py`, `transport.py`, `connect.py`, and
  `client.py`. All symbols re-exported from top-level for backwards compatibility.
- **Ping-on-connect validation** — all connect functions automatically ping the
  device and reject non-DongLoRa devices within 200 ms (matches Rust v0.2.0).
- **`try_connect(timeout)`** — non-blocking alternative to `connect()`. Returns
  an error immediately if no device is found.
- **`connect_default()`** — convenience wrapper with default timeout.
- **`connect_mux_auto(timeout)`** — mux-only connection, never falls back to USB
  serial. Equivalent of Rust client's "sticky mux" behaviour.
- **`default_socket_path()`** — resolve the preferred mux socket path.
- **`validate(ser)`** — public function for manual device validation.
- **Payload size validation** — `encode_command("Transmit", ...)` rejects
  payloads exceeding 256 bytes.
- **`Bandwidth` and `ErrorCode` enums** — `IntEnum` types matching the Rust
  definitions.
- **`RadioConfig` TypedDict** — typed dict for radio configuration.
- **New constants** — `MAX_PAYLOAD`, `RADIO_CONFIG_SIZE`, `CMD_TAG_*`,
  `RESP_TAG_*`, `ERROR_*` tag/error constants.
- **`py.typed` marker** — PEP 561 support for type checkers.
- **Comprehensive test suite** — 46 tests ported from the Rust client covering
  protocol roundtrips, COBS framing, client send/recv, firmware wire
  compatibility.
- **GitHub Actions CI** — ruff lint + format, pytest on Python 3.10–3.13, PyPI
  publish on tag.
- **Strict ruff linting** — E, W, F, I, UP, B, C4, ARG, SIM, RUF rules.

### Breaking changes

- **Package renamed back to `donglora`** — the short-lived `donglora-python`
  name is reverted. Import as `import donglora` (was always the intended API).
- **`connect()` no longer falls through from mux to USB serial** — if a mux
  socket file exists, the function commits to the mux or raises an error
  (matches Rust v0.2.1). This prevents port-stealing race conditions.
- **Sticky mux global removed** — the module-level `_mux_mode` variable and
  `_reconnect_mux()` are gone. Use `connect_mux_auto()` for mux-only mode.
- **`DEFAULT_CONFIG` now includes `cad: 1`** — previously relied on
  `encode_config()` defaulting it.

### Fixes

- Fixed broken dependency paths that prevented `uv sync` from resolving.
- Replaced `print()` calls with `logging` in discovery module.

## 0.1.0 — 2026-04-06

Initial release.
