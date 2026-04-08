# Changelog

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
