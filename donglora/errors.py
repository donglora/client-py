"""Wire error codes + Python exception hierarchy.

``ErrorCode`` mirrors PROTOCOL.md §7. ``DongloraError`` subclasses are
raised by the high-level :class:`donglora.dongle.Dongle` so callers can
catch specific failures (e.g. ``ChannelBusy``) without inspecting codes.
"""

from __future__ import annotations

import enum


class ErrorCode(enum.IntEnum):
    """Wire-level error code (u16 LE). Values assigned by PROTOCOL.md §7."""

    # Synchronous (0x0001..=0x00FF)
    EPARAM = 0x0001
    ELENGTH = 0x0002
    ENOT_CONFIGURED = 0x0003
    EMODULATION = 0x0004
    EUNKNOWN_CMD = 0x0005
    EBUSY = 0x0006

    # Asynchronous (0x0100..=0x01FF)
    ERADIO = 0x0101
    EFRAME = 0x0102
    EINTERNAL = 0x0103

    @classmethod
    def from_u16(cls, raw: int) -> ErrorCode | int:
        """Return the named variant if recognised, otherwise the raw int."""
        try:
            return cls(raw)
        except ValueError:
            return raw


# ── Python exception hierarchy ─────────────────────────────────────


class DongloraError(Exception):
    """Base class for all DongLoRa client errors."""


class FrameError(DongloraError):
    """COBS decode, CRC check, or length check failed on an inbound frame."""


class TimeoutError_(DongloraError):
    """Command response not received within the configured deadline."""


class DeviceError(DongloraError):
    """The device returned an ``ERR`` frame."""

    def __init__(self, code: ErrorCode | int, *, tag: int | None = None):
        self.code = code
        self.tag = tag
        name = code.name if isinstance(code, ErrorCode) else f"0x{int(code):04X}"
        super().__init__(f"device error {name} (tag={tag})")


class NotConfiguredError(DeviceError):
    """Mapped from ``ERR(ENOTCONFIGURED)``."""


class BusyError(DeviceError):
    """Mapped from ``ERR(EBUSY)``."""


class ParamError(DeviceError):
    """Mapped from ``ERR(EPARAM)``."""


class LengthError(DeviceError):
    """Mapped from ``ERR(ELENGTH)``."""


class ModulationError(DeviceError):
    """Mapped from ``ERR(EMODULATION)``."""


class UnknownCommandError(DeviceError):
    """Mapped from ``ERR(EUNKNOWN_CMD)``."""


class RadioError(DeviceError):
    """Mapped from ``ERR(ERADIO)`` — SPI error or unexpected hardware state."""


class InternalError(DeviceError):
    """Mapped from ``ERR(EINTERNAL)`` — firmware bug or invariant violation."""


_SPECIALISATIONS: dict[int, type[DeviceError]] = {
    ErrorCode.EPARAM: ParamError,
    ErrorCode.ELENGTH: LengthError,
    ErrorCode.ENOT_CONFIGURED: NotConfiguredError,
    ErrorCode.EMODULATION: ModulationError,
    ErrorCode.EUNKNOWN_CMD: UnknownCommandError,
    ErrorCode.EBUSY: BusyError,
    ErrorCode.ERADIO: RadioError,
    ErrorCode.EINTERNAL: InternalError,
}


def device_error(code: ErrorCode | int, *, tag: int | None = None) -> DeviceError:
    """Construct the most specific :class:`DeviceError` subclass for *code*."""
    cls = _SPECIALISATIONS.get(int(code), DeviceError)
    return cls(code, tag=tag)


# ── TX-specific non-error results ──────────────────────────────────


class ChannelBusy(DongloraError):
    """CAD detected activity and TX was not attempted. Retry with new tag."""


class Cancelled(DongloraError):
    """A queued TX was cancelled before it reached the air (SET_CONFIG
    or disconnect interrupted the queue).
    """
